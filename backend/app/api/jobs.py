"""Jobs API (PLAN Phase 3): upload, status, SSE progress, source, draft review, approval, export.

Responses with patient data (source, draft, IPS) go only to the job's reviewer and carry
``Cache-Control: no-store``. Errors are typed and PHI-free (`app.api.errors`). Nothing here logs
document content: log lines carry job ids, codes and counts only.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Header, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, CurrentUserDep, ServicesDep
from app.api.errors import ApiError
from app.db.models import ApprovedBundle, Draft, Job, JobEvent, JobSource, ReviewActionRecord
from app.pipeline.ingest import MAX_PDF_BYTES, MAX_TEXT_BYTES
from app.pipeline.run import summarise_validation
from app.pipeline.validate import MatchboxError
from app.review.approve import attest_bundle, attester_mode
from app.review.draft import DraftState, ReviewError, apply_actions, approval_blockers
from app.review.view import ApprovedInfo, assemble_effective, build_draft_view
from app.schemas.api import (
    TERMINAL_JOB_EVENTS,
    ApprovalOut,
    ApproveRequest,
    ConfirmAction,
    CurrentUserOut,
    DraftOut,
    DraftUpdate,
    EditAction,
    JobError,
    JobEventOut,
    JobOut,
    JobStatus,
    SegmentOut,
    SourceOut,
)
from app.services import Services

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])

SSE_WAKEUP_S: Final = 10.0
"""SSE streams re-read the event table at least this often (and send a keep-alive)."""

_PDF = "application/pdf"
_EXTENSIONS: Final = {
    ".txt": "text/plain",
    ".text": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".json": "application/json",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".pdf": _PDF,
}
_SUPPORTED: Final = frozenset(_EXTENSIONS.values()) | {"text/x-markdown", "application/csv"}


# ---- helpers ----------------------------------------------------------------------------------


def _job_out(job: Job, draft_version: int | None, approved: ApprovedBundle | None) -> JobOut:
    error = (
        JobError(step=job.error_step, code=job.error_code, message=job.error_message or "")
        if job.error_code
        else None
    )
    return JobOut(
        id=job.id,
        status=JobStatus(job.status),
        created_at=job.created_at,
        updated_at=job.updated_at,
        media_type=job.media_type.split(";")[0],
        size_bytes=job.size_bytes,
        extractor=job.extractor,
        current_step=job.current_step,
        error=error,
        draft_version=draft_version,
        approved_at=approved.approved_at if approved else None,
    )


def _load_job(session: Session, job_id: UUID, user: CurrentUser) -> Job:
    job = session.get(Job, job_id)
    # Someone else's job is reported as missing, not forbidden (no existence oracle).
    if job is None or job.created_by != user.id:
        raise ApiError(404, "job_not_found", "No such job.")
    return job


def _require_draft(session: Session, job: Job, *, lock: bool = False) -> Draft:
    if job.status not in (JobStatus.REVIEW, JobStatus.APPROVED):
        raise ApiError(409, "draft_not_ready", "The draft is not ready yet.")
    query = select(Draft).where(Draft.job_id == job.id)
    if lock:
        query = query.with_for_update()
    draft = session.scalar(query)
    if draft is None:
        raise ApiError(409, "draft_not_ready", "The draft is not ready yet.")
    return draft


def _resolve_media_type(data: bytes, content_type: str | None, filename: str | None) -> str:
    if b"%PDF-" in data[:1024]:
        return _PDF
    ext = ""
    if filename and "." in filename:
        ext = "." + filename.rsplit(".", 1)[1].lower()
    declared = (content_type or "").split(";")[0].strip().lower()
    charset = ""
    if content_type and "charset=" in content_type.lower():
        charset = "; charset=" + content_type.lower().split("charset=", 1)[1].split(";")[0].strip()
    if ext in _EXTENSIONS and _EXTENSIONS[ext] != _PDF:
        return _EXTENSIONS[ext] + charset
    if declared in _SUPPORTED and declared != _PDF:
        return declared + charset
    if ext == ".pdf" or declared == _PDF:
        raise ApiError(400, "corrupt_document", "The file is declared as PDF but is not a PDF.")
    raise ApiError(
        415,
        "unsupported_media_type",
        "Supported formats: plain text / Markdown, JSON, CSV and PDF with a text layer.",
    )


def _view(services: Services, job: Job, draft: Draft) -> DraftOut:
    state = DraftState.model_validate(draft.state)
    approved = None
    if job.status == JobStatus.APPROVED:
        with services.session() as session:
            row = session.get(ApprovedBundle, job.id)
        if row is not None:
            approved = ApprovedInfo(at=row.approved_at, attester_mode=row.attester_mode)  # type: ignore[arg-type]
    return build_draft_view(
        state,
        job_id=job.id,
        version=draft.version,
        status=JobStatus(job.status),
        now=services.now(),
        created_at=job.created_at,
        approved=approved,
    )


# ---- routes -----------------------------------------------------------------------------------


@router.get("/me")
def me(user: CurrentUserDep, services: ServicesDep) -> CurrentUserOut:
    return CurrentUserOut(
        id=user.id, display_name=user.display_name, auth_mode=services.settings.auth_mode.value
    )


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def create_job(
    services: ServicesDep,
    user: CurrentUserDep,
    file: Annotated[UploadFile, File(description="txt/md, json, csv or text-layer pdf")],
) -> JobOut:
    data = file.file.read(MAX_PDF_BYTES + 1)
    if not data.strip():
        raise ApiError(400, "empty_document", "The file is empty.")
    media_type = _resolve_media_type(data, file.content_type, file.filename)
    limit = MAX_PDF_BYTES if media_type == _PDF else MAX_TEXT_BYTES
    if len(data) > limit:
        raise ApiError(
            413, "document_too_large", f"The file is larger than {limit // (1024 * 1024)} MiB."
        )

    job_id = uuid4()
    object_key = f"jobs/{job_id}/original"
    services.store.put(object_key, data, media_type)
    with services.session() as session, session.begin():
        job = Job(
            id=job_id,
            status=JobStatus.QUEUED,
            created_by=user.id,
            media_type=media_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            object_key=object_key,
            extractor=services.settings.extractor.value,
        )
        session.add(job)
        services.audit(
            session,
            actor=user.id,
            action="job.created",
            job_id=job_id,
            media_type=media_type.split(";")[0],
            size_bytes=len(data),
        )
    services.record_event(job_id, "job", "queued")
    logger.info("job %s created (%s, %d bytes)", job_id, media_type.split(";")[0], len(data))
    services.enqueue(job_id)
    with services.session() as session:
        job = _load_job(session, job_id, user)
        draft = session.get(Draft, job_id)
        return _job_out(job, draft.version if draft else None, None)


@router.get("/jobs")
def list_jobs(services: ServicesDep, user: CurrentUserDep) -> list[JobOut]:
    with services.session() as session:
        jobs = session.scalars(
            select(Job).where(Job.created_by == user.id).order_by(Job.created_at.desc()).limit(20)
        ).all()
        out = []
        for job in jobs:
            draft = session.get(Draft, job.id)
            out.append(
                _job_out(job, draft.version if draft else None, session.get(ApprovedBundle, job.id))
            )
        return out


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, services: ServicesDep, user: CurrentUserDep) -> JobOut:
    with services.session() as session:
        job = _load_job(session, job_id, user)
        draft = session.get(Draft, job_id)
        return _job_out(job, draft.version if draft else None, session.get(ApprovedBundle, job_id))


def _events_after(
    services: Services, job_id: UUID, after: int
) -> tuple[list[JobEventOut], str | None]:
    """Events after ``after`` and the job's status."""
    with services.session() as session:
        rows = session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.seq > after)
            .order_by(JobEvent.seq)
        ).all()
        job = session.get(Job, job_id)
        events = [
            JobEventOut(seq=r.seq, step=r.step, status=r.status, detail=r.detail, at=r.created_at)
            for r in rows
        ]
        return events, job.status if job else None


_SETTLED = frozenset({JobStatus.REVIEW, JobStatus.APPROVED, JobStatus.FAILED})


def _check_job(services: Services, job_id: UUID, user: CurrentUser) -> None:
    with services.session() as session:
        _load_job(session, job_id, user)


@router.get(
    "/jobs/{job_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def job_events(
    job_id: UUID,
    request: Request,
    services: ServicesDep,
    user: CurrentUserDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Server-sent events: every stored event after ``Last-Event-ID``, then live ones, until
    the job reaches review / failure / approval. ``data`` is a `JobEventOut` (no PHI)."""
    await run_in_threadpool(_check_job, services, job_id, user)
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def stream() -> AsyncIterator[str]:
        last = start
        yield "retry: 3000\n\n"
        async with services.bus.subscribe(job_id) as subscription:
            while True:
                events, job_status = await run_in_threadpool(_events_after, services, job_id, last)
                for event in events:
                    last = event.seq
                    yield f"id: {event.seq}\ndata: {event.model_dump_json()}\n\n"
                    if event.step == "job" and event.status in TERMINAL_JOB_EVENTS:
                        return
                if not events and job_status in _SETTLED:
                    return  # resumed after the terminal event: nothing more will come
                if await request.is_disconnected():
                    return
                if await subscription.next(SSE_WAKEUP_S) is None:
                    yield ": keep-alive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}/source")
def get_source(job_id: UUID, services: ServicesDep, user: CurrentUserDep) -> SourceOut:
    with services.session() as session:
        job = _load_job(session, job_id, user)
        source = session.get(JobSource, job_id)
        if source is None:
            raise ApiError(409, "source_not_ready", "The document has not been processed yet.")
        document: dict[str, Any] = source.document
        is_pdf = job.media_type.startswith(_PDF)
        return SourceOut(
            media_type=document["media_type"],
            page_count=document.get("page_count", 1),
            pages_without_text=list(document.get("pages_without_text", [])),
            segments=[SegmentOut.model_validate(s) for s in document["segments"]],
            original_url=f"/api/jobs/{job_id}/source/original" if is_pdf else None,
        )


@router.get("/jobs/{job_id}/source/original", response_class=Response)
def get_original(job_id: UUID, services: ServicesDep, user: CurrentUserDep) -> Response:
    with services.session() as session:
        job = _load_job(session, job_id, user)
        object_key, media_type = job.object_key, job.media_type
    data = services.store.get(object_key)
    return Response(
        data,
        media_type=media_type,
        headers={"Cache-Control": "no-store", "Content-Disposition": "inline"},
    )


@router.get("/jobs/{job_id}/draft")
def get_draft(job_id: UUID, services: ServicesDep, user: CurrentUserDep) -> DraftOut:
    with services.session() as session:
        job = _load_job(session, job_id, user)
        return _view(services, job, _require_draft(session, job))


def _payload(action: Any) -> dict[str, Any] | None:
    if isinstance(action, EditAction):
        return {"value": action.value}
    if isinstance(action, ConfirmAction) and action.clinical_status:
        return {"clinical_status": action.clinical_status}
    return None


@router.put("/jobs/{job_id}/draft")
def update_draft(
    job_id: UUID, body: DraftUpdate, services: ServicesDep, user: CurrentUserDep
) -> DraftOut:
    """Apply reviewer actions (all or nothing) to draft ``version``; returns the new draft."""
    with services.session() as session, session.begin():
        job = _load_job(session, job_id, user)
        draft = _require_draft(session, job, lock=True)
        if job.status == JobStatus.APPROVED:
            raise ApiError(409, "already_approved", "The draft has been approved.")
        if body.version != draft.version:
            raise ApiError(
                409,
                "version_conflict",
                "The draft has changed; reload it.",
                [{"current_version": draft.version}],
            )
        state = DraftState.model_validate(draft.state)
        try:
            state = apply_actions(state, body.actions, actor=user.id, now=services.now())
        except ReviewError as exc:
            raise ApiError(422, exc.code, exc.message, [{"path": exc.path}]) from exc
        draft.state = state.model_dump(mode="json")
        draft.version += 1
        for action in body.actions:
            session.add(
                ReviewActionRecord(
                    job_id=job_id,
                    actor=user.id,
                    action=action.action,
                    path=action.path,
                    payload=_payload(action),
                    draft_version=draft.version,
                )
            )
        services.audit(
            session,
            actor=user.id,
            action="draft.updated",
            job_id=job_id,
            version=draft.version,
            actions=[{"action": a.action, "path": a.path} for a in body.actions],
        )
        return _view(services, job, draft)


@router.post("/jobs/{job_id}/approve")
def approve(
    job_id: UUID, body: ApproveRequest, services: ServicesDep, user: CurrentUserDep
) -> ApprovalOut:
    """Approve the draft (D-4): attest, re-assemble, validate, store. Blocked until the
    patient's name and birth date are present and derived values are confirmed."""
    with services.session() as session, session.begin():
        job = _load_job(session, job_id, user)
        draft = _require_draft(session, job, lock=True)
        if job.status == JobStatus.APPROVED:
            raise ApiError(409, "already_approved", "The draft has already been approved.")
        if body.version != draft.version:
            raise ApiError(
                409,
                "version_conflict",
                "The draft has changed; reload it.",
                [{"current_version": draft.version}],
            )
        state = DraftState.model_validate(draft.state)
        blockers = approval_blockers(state)
        if blockers:
            raise ApiError(
                409,
                "approval_blocked",
                "The draft cannot be approved yet.",
                [{"code": b.code.value, "path": b.path} for b in blockers],
            )
        now = services.now()
        assembly = assemble_effective(state, now=now)
        bundle = attest_bundle(
            assembly.bundle, role=body.role, reviewer_name=user.display_name, at=now
        )
        validation = None
        if services.validator is not None:
            try:
                validation = summarise_validation(services.validator(bundle))
            except MatchboxError as exc:
                raise ApiError(
                    503, "validator_unavailable", "The FHIR validator is not reachable."
                ) from exc
            if not validation.passed:
                raise ApiError(
                    422,
                    "validation_failed",
                    "The IPS Bundle does not validate; it was not approved.",
                    [
                        {
                            "errors": validation.errors,
                            "unmatched_entries": validation.unmatched_entries,
                        },
                        *[i.model_dump() for i in validation.issues if i.severity != "warning"],
                    ],
                )
        mode = attester_mode(body.role)
        session.add(
            ApprovedBundle(
                job_id=job_id,
                bundle=bundle.to_fhir(),
                approved_by=user.id,
                reviewer_role=body.role.value,
                attester_mode=mode,
                draft_version=draft.version,
                validation=validation.model_dump(mode="json") if validation else None,
                approved_at=now,
            )
        )
        job.status = JobStatus.APPROVED
        services.audit(
            session,
            actor=user.id,
            action="draft.approved",
            job_id=job_id,
            version=draft.version,
            role=body.role.value,
            attester_mode=mode,
            validation_passed=validation.passed if validation else None,
        )
    services.record_event(job_id, "job", "approved")
    logger.info("job %s approved", job_id)
    return ApprovalOut(
        job_id=job_id,
        approved_at=now,
        approved_by=user.id,
        attester_mode=mode,
        validation=validation,
        ips_url=f"/api/jobs/{job_id}/ips",
    )


@router.get("/jobs/{job_id}/ips", response_class=JSONResponse)
def get_ips(job_id: UUID, services: ServicesDep, user: CurrentUserDep) -> JSONResponse:
    """The approved IPS Bundle (FHIR JSON) as a download."""
    with services.session() as session:
        job = _load_job(session, job_id, user)
        approved = session.get(ApprovedBundle, job.id)
        if approved is None:
            raise ApiError(409, "not_approved", "The draft has not been approved yet.")
        services.audit(session, actor=user.id, action="ips.downloaded", job_id=job_id)
        session.commit()
        return JSONResponse(
            approved.bundle,
            media_type="application/fhir+json",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="ips-{job_id}.json"',
            },
        )
