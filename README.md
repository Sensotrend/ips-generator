# IPS Generator

Turn arbitrary healthcare documents into a valid **International Patient Summary (IPS)**: a FHIR R4
document Bundle conforming to the [HL7 IPS IG](https://hl7.org/fhir/uv/ips/) (`hl7.fhir.uv.ips#2.0.1`).
A human reviews and approves every result in a mobile-friendly PWA.

> **Status: Phases 1–3 in progress.** The extraction pipeline (ingest → extract → ground → assemble →
> validate), the eval harness, the job API with an RQ worker, and the review PWA (upload → progress →
> review with source highlights → approve → download) run locally (see [Running locally](#running-locally)).
> Development only: a fixed dev reviewer (no OIDC yet). Terminology coding runs its free deterministic
> pass (`TERMINOLOGY_MODE`); the Claude tool loop is built but untested live, and the repair loop is
> Phase 2. See [PLAN.md](PLAN.md) for the roadmap and decisions.

## Purpose

- **Input:** plaintext, JSON, CSV and text-layer PDF today. Scans, photos, DOCX, HL7 v2 and CDA are
  planned (Phase 4). Documents may be in Finnish, Swedish or English.
- **Output:** an IPS Bundle with the required sections (Medication Summary, Allergies & Intolerances,
  Problem List), plus History of Past Illness where applicable.
- **Human in the loop:** nothing is autonomous. The output is a draft until a person approves it.

### Design rules

These are non-negotiable (see [CLAUDE.md](CLAUDE.md)):

- The LLM fills a flat **intermediate schema**. It never emits FHIR. FHIR is built only by
  deterministic Python mappers.
- **No invented clinical codes.** Codes come from terminology-server lookups. Otherwise the text is
  kept uncoded. Only codes fixed by the IPS IG are allowed, as named constants.
- Every extracted fact keeps its `source_quote` and `page`. A deterministic **grounding check**
  drops or flags facts whose quote is not in the source text.
- A Matchbox validation pass against the IPS profile is the quality gate, not model self-assessment.
- No real patient data in the repo, fixtures, logs or prompts. No PHI in the PWA service-worker cache.

## Architecture

```
PWA (React + Vite)            upload → progress → review & edit → approve → export     [MVP]
        │
API (FastAPI) + RQ worker     jobs, SSE status, review, approval, audit                [MVP, dev auth]
        │
Pipeline (backend/app/pipeline)
  1. ingest      normalise to located text segments (line / row / JSON path / page)    [done]
  2. classify    document type, language, relevant sections                            [planned]
  3. extract     Claude, structured outputs → intermediate JSON                        [done]
  4. ground      check each source_quote against the source text                       [done]
  5. terminology lookups + Claude tool loop over a FHIR terminology server            [deterministic done; LLM loop untested live]
  6. assemble    deterministic mappers → IPS document Bundle                           [done]
  7. validate    Matchbox $validate (IPS IG); targeted repair of the JSON, not FHIR    [validate done]
  8. review      human approval (Composition.attester) → stored Bundle                [done; Provenance/FHIR server planned]
```

| Path | Contents |
|---|---|
| `backend/app/pipeline/` | Pipeline steps |
| `backend/app/schemas/` | `intermediate.py` (LLM schema), `source.py` (ingest contract), `api.py` |
| `backend/app/fhir/` | Own thin Pydantic v2 FHIR R4 models and the per-section mappers |
| `backend/app/llm/` | Provider-agnostic client, per-step model config (`models.py`), versioned prompts in `prompts/` |
| `frontend/` | React + TypeScript + Vite PWA (`vite-plugin-pwa`, TanStack Query) |
| `evals/` | Synthetic eval dataset (26 FI/SV/EN documents) and the scoring harness |
| `infra/` | Docker Compose services and Matchbox config |

**Stack:** Python 3.12, FastAPI, Pydantic v2, the official `anthropic` SDK, uv, ruff, mypy, pytest;
React, TypeScript, Vite, Vitest; Postgres, Redis, MinIO and Matchbox via Docker Compose.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (it installs Python 3.12)
- Node.js 24 and npm
- Docker with Compose, for Matchbox and the other local services
- An Anthropic API key, only for live LLM calls. **Use synthetic data only** with the Anthropic API
  (see PLAN D-5).

## Installation

```sh
git clone <repo-url> && cd ips-generator

# Backend
cd backend && uv sync --locked && cd ..

# Frontend
cd frontend && npm ci && cd ..

# Configuration: copy and edit. The backend reads the process environment; it does not load .env itself.
cp .env.example .env
```

Never commit `.env`. To use it, export it into your shell, e.g. `set -a; source .env; set +a`.

### Local services

```sh
docker compose --env-file .env -f infra/docker-compose.yml up -d
```

This starts Postgres, Redis, MinIO (with a documents bucket) and Matchbox. The first Matchbox start
installs the IPS IG and takes several minutes. Wait until it reports healthy
(`docker compose -f infra/docker-compose.yml ps`). Matchbox listens on `http://localhost:8080` and
uses `tx.fhir.org` as terminology server, which is for development only.

## Running locally

The whole app (API, worker, PWA) runs locally against the Compose services. **Development only:**
the API refuses to start unless `APP_ENV=development`, and every request is made as a fixed dev
reviewer ("Dev Reviewer"); OIDC login is not implemented yet. Without an Anthropic key, use the
**replay extractor** (`EXTRACTOR=replay`): it returns the gold extraction for any of the eval
documents in `evals/dataset/*/document.*` (byte-identical uploads only) and fails every other upload
with "replay extractor has no answer for this document". Synthetic data only.

### Option A: everything in Docker

```sh
# Ports: if 5432 / 8000 are taken on your machine, pick others.
POSTGRES_PORT=5433 API_PORT=8010 \
  docker compose -f infra/docker-compose.yml --profile app up -d --build
```

The `app` profile adds `api` (runs `alembic upgrade head`, then uvicorn on `API_PORT`) and `worker`
(RQ, `python -m app.worker`), both with `EXTRACTOR=replay` unless you set `EXTRACTOR=claude` and
`ANTHROPIC_API_KEY`. Then start the PWA dev server, pointing its `/api` proxy at the API:

```sh
cd frontend && VITE_API_PROXY=http://localhost:8010 npm run dev   # open the printed URL
```

### Option B: API and worker as local processes

Terminal 1:

```sh
# start postgres, redis, minio, matchbox
POSTGRES_PORT=5433 docker compose -f infra/docker-compose.yml up -d

cd backend
export APP_ENV=development EXTRACTOR=replay \
  DATABASE_URL=postgresql://ips:ips-dev-password@localhost:5433/ips \
  S3_ACCESS_KEY=ips-dev-access S3_SECRET_KEY=ips-dev-secret-key
# migrate
uv run alembic upgrade head
# start API
uv run uvicorn app.main:app --reload --port 8010
```

Terminal 2:

```sh
cd backend
export APP_ENV=development EXTRACTOR=replay \
  DATABASE_URL=postgresql://ips:ips-dev-password@localhost:5433/ips \
  S3_ACCESS_KEY=ips-dev-access S3_SECRET_KEY=ips-dev-secret-key
# start worker (--simple: no fork; needed on macOS)
uv run python -m app.worker --simple
```

Terminal 3:

```sh
cd frontend && VITE_API_PROXY=http://localhost:8010 npm run dev
```

Without Matchbox running, set `VALIDATE_WITH_MATCHBOX=false` (approval then skips validation).

### Walk-through

1. Upload e.g. `evals/dataset/fi01_discharge_internal_txt/document.txt`,
   `evals/dataset/en01_discharge_resp_pdf/document.pdf` or a CSV case. Progress streams over SSE.
2. Review: tap a fact to see its quote highlighted in the source (line/row/JSON path segments, or
   the PDF text layer). Accept, edit or reject facts; confirm assumed allergy statuses and values
   derived from an identity code. Flags show relocated/fuzzy quotes, unverified sections, etc.
3. Approve as the patient (attester mode `personal`) or as a clinician (`professional`). Approval is
   blocked until the patient's name and birth date are present and derived values are confirmed,
   and it requires the attested Bundle to pass Matchbox validation.
4. Download the approved IPS Bundle (FHIR JSON).

The same flow over plain HTTP: `POST /api/jobs` (multipart `file`), `GET /api/jobs/{id}`,
`GET /api/jobs/{id}/events` (SSE), `GET /api/jobs/{id}/source[/original]`,
`GET|PUT /api/jobs/{id}/draft`, `POST /api/jobs/{id}/approve`, `GET /api/jobs/{id}/ips`. OpenAPI docs
are at `/docs` on the API port.

Stop everything with `docker compose -f infra/docker-compose.yml --profile app down` (volumes are
kept; add `-v` to wipe them). Originals in MinIO are **not encrypted at rest** in this setup.

## Build, lint and test

Backend (from `backend/`):

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
uv run pytest                       # unit tests
```

The tests in `tests/integration/` need Matchbox running. `python3 infra/scripts/validate_sample.py`
validates the IG example Bundles against it.

Frontend (from `frontend/`):

```sh
npm run lint
npm run format:check
npm test -- --run
npm run build                       # type-check + production build into dist/
```

CI (`.github/workflows/ci.yml`) runs these same checks on every push and pull request.

## Usage

### Run the API and the PWA

See [Running locally](#running-locally).

### Run the pipeline directly

For one paid smoke test of extraction on a synthetic Finnish discharge summary:

```sh
cd backend
ANTHROPIC_API_KEY=... uv run python -m scripts.smoke_extract
```

### Configure models

Each pipeline step has its own model and effort setting in
[backend/app/llm/models.py](backend/app/llm/models.py). Override them with environment variables
`IPS_MODEL_<STEP>` and `IPS_EFFORT_<STEP>` (`low`, `medium`, `high` or `none`). See `.env.example`.
Never hardcode a model id anywhere else. Prompts live in `backend/app/llm/prompts/`. Bump the version
when you change one.

### Run the evals

The harness scores extraction against gold data and validates assembled Bundles. Run it from
`backend/`:

```sh
# Free self-test: gold.json used as the prediction
uv run python ../evals/run_evals.py --predictions gold

# Also validate every Bundle in Matchbox
uv run python ../evals/run_evals.py --predictions gold --validate

# PAID: real extraction. Prints a cost estimate and asks first.
ANTHROPIC_API_KEY=... uv run python ../evals/run_evals.py --predictions live --validate \
    --max-cost-usd 3 --append-results

# Re-score a saved run without API calls
uv run python ../evals/run_evals.py --predictions cached --run ../evals/runs/<run dir>
```

Options, run output and recorded results are in [evals/RESULTS.md](evals/RESULTS.md). The dataset and
its gold-authoring rules are described in [evals/dataset/README.md](evals/dataset/README.md).

## Git workflow

Two developers, each with several parallel Claude chats, all pushing to `origin`. We move fast, so the
rules are light, but they keep parallel work from colliding.

### Principles
- `main` is the integration branch and should stay green (ruff, mypy, pytest). There are no required
  approvals and no required PRs: either developer, or any Claude chat acting for them, may land commits on
  `main` directly. Check before landing, not after.
- **Linear history, rebase only.** Never create merge commits; land work with `git rebase origin/main`
  followed by a fast-forward push (`git push origin HEAD:main`). If the push is rejected, fetch, rebase
  and retry. Never force-push `main`.
- Branches are short-lived and cover one task from `PLAN.md`. Land them within a day or two.
- **One chat = one worktree = one branch.** Never run two chats in the same checkout; they would fight
  over the working tree and index.

### Branches and worktrees
- Name branches `<initials>/<topic>`, for example `sr/ground-quotes`.
- Start from a freshly fetched `origin/main`, with the worktree outside the repo:
  ```sh
  git fetch --prune origin
  git worktree add ../ips-generator-wt/<topic> -b <initials>/<topic> origin/main
  ```
- Claude Code chats use `claude --worktree`; subagents that write code use `isolation: "worktree"`.
  Read-only agents (search, review) may share the parent's checkout.
- Gitignored files do not follow a worktree: copy `.env`, then run `uv sync` and `npm ci`. Parallel
  worktrees must not start the Compose stack twice on the same ports. Start it once and share it, or set
  `COMPOSE_PROJECT_NAME` and port overrides (see [Running locally](#running-locally)).
- After landing, remove the worktree and branch: `git worktree remove <path>`, `git branch -d <branch>`.
  Occasionally run `git fetch --prune` and `git worktree prune`.

### Fetching and pushing
- **Start of every chat or task:** `git fetch --prune origin`; look at `git log HEAD..origin/main --oneline`;
  rebase if `main` moved.
- **Look at other branches too**, not only `main`: `git branch -r --no-merged origin/main` (and `gh pr list`
  if you use PRs) shows what the other developer is working on, so you avoid overlapping work. Always
  *base* your work on `origin/main`, never on someone else's unmerged branch.
- **Push at least hourly.** Push your branch to `origin` after the first commit and at least once an hour
  while working, plus at the end of every session, so nothing lives only on one laptop. WIP is fine on
  your own branch (`git push -u origin HEAD`; after a rebase use `--force-with-lease`, on your own
  branches only).
- **Land on `main`** when a task is done and checks pass: fetch, rebase onto `origin/main`, run the
  tests, `git push origin HEAD:main`. Pipeline changes also meet the definition of done below. A PR is
  optional (use one when you want a second opinion or CI before landing).
- Commit small, one logical change per commit; the message says why, imperative mood.
- Never commit `.env`, secrets or real patient data (see [CLAUDE.md](CLAUDE.md)).

### Files that conflict often
- `PLAN.md`: tick your task in the same change that completes it and touch only that task's lines.
  Restructure it in a separate small commit and land it quickly.
- `evals/RESULTS.md`: append entries (date and branch); on conflict keep both.
- `backend/uv.lock`, `package-lock.json`: don't hand-merge. Take `origin/main`'s version, then rerun
  `uv lock` or `npm install`. Land dependency changes quickly in their own commit.
- Prompts in `backend/app/llm/prompts/`: the version bump goes in the same commit as the change; after a
  rebase conflict, take the next free version number.
- `backend/app/llm/models.py` and `backend/app/schemas/intermediate.py`: everything depends on them;
  tell the other developer before changing them.

## Definition of done for pipeline changes

- `pytest` passes and the mappers are covered by tests.
- Generated Bundles validate against the IPS IG in Matchbox with no errors.
- For extraction or prompt changes, run the evals and record the result in `evals/RESULTS.md`.

## Further reading

- [PLAN.md](PLAN.md): architecture, decisions (D1–D8, D-1–D-11), model selection, phased task list
- [CLAUDE.md](CLAUDE.md): project rules for contributors and coding agents
