# PLAN: Healthcare Document → IPS FHIR Extraction Agent + PWA

> Living plan. Work phase by phase. Tick boxes (`- [x]`) as tasks are completed and
> add short notes under a task when a decision deviates from this plan.

## 1. Goal

Take arbitrary healthcare documents (PDF, scanned images, photos, DOCX, plain text,
HL7 v2, CDA) and produce a **valid International Patient Summary (IPS)** FHIR R4
document Bundle, reviewed and approved by a human, via a mobile-friendly PWA.

### Non-goals (for now)
- Autonomous clinical decision-making — every output is human-reviewed.
- Writing back into an EHR (later phase, via SMART on FHIR).
- Offline storage of patient data on devices.
- Multi-document upload and merging of several IPS summaries: possible future enhancements, see D-12 and Phase 4.

## 2. Architecture

```
PWA (React + Vite + vite-plugin-pwa)
  upload / camera → progress (SSE) → review & edit → approve → export
        │  HTTPS + OIDC
API (FastAPI)  — jobs, SSE status, review endpoints, audit log
        │  job queue (RQ/Celery for MVP → Temporal later)
Extraction pipeline
  1. Ingest & normalize   → pages, text, page images
  2. Classify & route     → doc type, language, relevant IPS sections
  3. LLM extraction       → intermediate JSON (structured outputs), every fact has source_quote + page
  4. Grounding check      → deterministic: source_quote must exist in source text; drop/flag otherwise
  5. Terminology coding   → Claude tool loop against terminology server (SNOMED CT, LOINC, ATC, ICD-10)
  6. FHIR assembly        → DETERMINISTIC Python mapper → IPS document Bundle
  7. Validate & repair    → FHIR Validator (IPS IG); targeted LLM repair of the *intermediate JSON*
                            (never the FHIR), re-run mapper, max 2 loops; else flag
  8. Human review         → approve → Provenance attached → stored in FHIR server
Storage: object storage (originals, encrypted) · Postgres (jobs, drafts, audit) · FHIR server (approved Bundles)
```

## 3. Key decisions (and why)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | LLM fills a **flat intermediate schema**, never raw FHIR | Raw FHIR is too large to constrain; LLM breaks references/cardinality. Mapper is testable. |
| D2 | Codes come **only** from terminology-server lookups | Prevents hallucinated codes. Keep `original_text`; omit code if uncertain. |
| D3 | Every extracted fact carries `source_quote` + `page` | Enables UI highlighting and deterministic grounding checks. |
| D4 | **Validator pass** = definition of done | Objective quality gate, not model self-assessment. |
| D5 | Workflow with bounded tool loops, not a free-form agent | Predictable cost/latency, auditable. |
| D6 | Model **per pipeline step**, set in one config file (`app/llm/models.py`, env-overridable); default `claude-opus-5-5`, official Anthropic Python SDK. See §8. | Native PDF/vision input, structured outputs, strict tool use. Cheaper steps can move to Sonnet once evals show no regression. |
| D7 | Required IPS sections always emitted; use explicit "no information"/"no known" when empty | IPS requires Medication Summary, Allergies & Intolerances, Problem List. |
| D8 | PWA service worker caches app shell only — never PHI | GDPR; lost/shared devices. |

## 4. Tech stack

- **Backend:** Python 3.12+, FastAPI, Pydantic v2, own thin Pydantic FHIR R4 models in `app/fhir/` (no `fhir.resources`, see §7.1 D-6), `anthropic` SDK
- **Queue:** RQ or Celery + Redis (MVP) → Temporal (Phase 5)
- **Docs:** `pypdf` / `pdfplumber`, LibreOffice headless (DOCX→PDF), `python-hl7`
- **FHIR validation/storage:** Matchbox (HAPI-based) with IPS IG package `hl7.fhir.uv.ips` (pin current published version); optionally HAPI FHIR JPA server for storage
- **Terminology:** `tx.fhir.org` for dev only → Snowstorm (SNOMED CT) / Ontoserver for prod (check licensing)
- **DB/storage:** Postgres, MinIO (dev) / S3-compatible (prod), encryption at rest
- **Frontend:** React + TypeScript + Vite, `vite-plugin-pwa` (Workbox), TanStack Query, `pdfjs-dist`
- **Auth:** OIDC (Keycloak in dev)
- **Dev env:** Docker Compose (api, worker, redis, postgres, minio, matchbox, keycloak)
- **Test data:** Synthea synthetic patients + hand-crafted messy documents. **No real patient data in the repo.**

## 5. Proposed repo layout

```
/backend
  app/api/            FastAPI routes (jobs, review, export, sse)
  app/pipeline/       ingest.py, classify.py, extract.py, ground.py, terminology.py,
                      assemble.py, validate.py, repair.py
  app/schemas/        intermediate.py (LLM extraction schema), api.py
  app/fhir/           mappers per section (allergies.py, medications.py, problems.py, ...)
  app/llm/            client.py, prompts/ (versioned prompt files)
  tests/              unit tests (mappers, grounding), integration (pipeline), fixtures/
/frontend             React PWA
/evals
  dataset/            input docs + expected intermediate JSON / expected IPS
  run_evals.py        metrics: per-section precision/recall, code accuracy, validator pass rate
/infra                docker-compose.yml, matchbox config, keycloak realm
PLAN.md  CLAUDE.md  README.md
```

## 6. Phases

> Each task ends with a **Claude Code model tag** — `[sonnet]`, `[opus]` or `[fable]` — saying which model
> to switch to (`/model`) before starting it. See §8.2 for what the tags mean.

### Phase 0 — Scaffolding
- [x] Repo layout as above; `pyproject.toml` (uv), ruff, mypy, pytest `[sonnet]`
  - Backend is a uv app (`package = false`), Python 3.12; mypy `strict` + pydantic plugin; tests split into
    `tests/unit`, `tests/integration`, `tests/fixtures` (pytest `--import-mode=importlib`). `GET /health` only.
  - `/evals` and `README.md` not created yet (Phase 1).
- [x] Frontend: Vite React TS app, ESLint, Prettier, Vitest `[sonnet]`
- [x] `infra/docker-compose.yml` with postgres, redis, minio, matchbox (IPS IG loaded, pinned version) `[opus]`
  - Matchbox `europe-west6-docker.pkg.dev/ahdis-ch/ahdis/matchbox:v4.1.21`; IPS IG `hl7.fhir.uv.ips#2.0.1`
    (current published, 2026-06-19), config in `infra/matchbox/application.yaml`, H2 DB on a volume.
    Matchbox uses `tx.fhir.org` as terminology server (dev only).
  - Upstream MinIO no longer publishes Docker images (CE archived); using the community build
    `pgsty/minio:RELEASE.2026-08-04T00-00-00Z` + a one-shot `minio-init` that creates the bucket.
  - Postgres `18.6`, Redis `8.8.3`. Keycloak, api and worker services deferred to Phase 3.
  - Sample validation: `python3 infra/scripts/validate_sample.py` validates the IG example Bundles in
    `backend/tests/fixtures/ips-examples/` against `Bundle-uv-ips|2.0.1` (0 errors).
- [x] `.env.example` (no secrets committed); `ANTHROPIC_API_KEY` read from env `[sonnet]`
  - Settings in `backend/app/config.py` (pydantic-settings, env only, no `.env` file loading).
- [x] `app/llm/models.py`: per-step model + effort config (§8.1), env-overridable `[sonnet]`
  - Env vars `IPS_MODEL_<STEP>` / `IPS_EFFORT_<STEP>`; `IPS_EFFORT_<STEP>=none` omits effort (for models without effort support).
- [x] CI: lint + tests for backend and frontend `[sonnet]`
  - `.github/workflows/ci.yml`; frontend job expects npm scripts `lint`, `format:check`, `test`, `build`.

**Done when:** `docker compose up` starts all services; `pytest` and `npm test` pass; Matchbox validates a sample IPS Bundle from the IG examples.

### Phase 1 — Evals + core extraction (plaintext, JSON, CSV, text-layer PDF → required sections)
- [x] Build eval dataset: 20+ synthetic docs (discharge summaries, prescriptions, lab reports, referral letters; FI/SV/EN) as plaintext, JSON, CSV and text-layer PDF, with gold intermediate JSON derived from the Synthea record each doc is rendered from `[opus]`
  - 26 hand-authored synthetic cases (fi 12, sv 6, en 6, mixed 2; txt 10, json 5, csv 4, pdf 7) in
    `evals/dataset/`, reproducible via `_build/build.py`. Synthea not used (deviation from D-3 proposal): hand-
    written records give controlled edge cases. Gold-authoring rules and feature matrix in `evals/dataset/README.md`.
  - `tests/unit/test_eval_dataset.py`: every gold quote grounds `exact` at its stated location.
- [x] `ingest.py`: normalise plaintext / JSON / CSV / text-layer PDF (`pdfplumber`) into located text segments; reject PDFs without a text layer with a clear error (OCR comes in Phase 4) `[opus]`
  - Contract in `app/schemas/source.py`. Segments: plaintext per line (`line N`), JSON per leaf (`$.a[2].b`),
    CSV per row (`row N`, header = row 1), PDF per page. `render_for_llm()` wraps segments in
    `<segment page=… locator=…>` tags that the model copies into `page`/`locator`.
  - Extra fields: `page_count`, `pages_without_text`. PDFs are rejected if fewer than half the pages have text.
  - Permissions-only encrypted PDFs (empty password) are accepted; password-protected ones are rejected.
  - Segment text is not escaped, so a document containing `</segment>` could confuse the markup. `extract.py`
    must treat the document as untrusted data (prompt-injection hardening).
  - Not yet: parser timeout/sandbox for hostile PDFs (Phase 3 worker).
- [x] Define intermediate schema (`app/schemas/intermediate.py`) for Patient, Allergies, Medications, Problems — every item has `source_quote`, `page`, `confidence` `[fable]`
  - Two layers: `IpsExtraction` (filled by the LLM, no code fields) and `EnrichedIps` (adds terminology codings,
    each with lookup provenance). `SCHEMA_VERSION = "1.0.0"`; bump it with the prompt version.
  - `page` is 1 for non-paged inputs; `locator` is copied from the ingest segment ("line 12", "row 4",
    "$.medications[2].name"), `None` for PDF pages.
  - `confidence` is `high`/`medium`/`low`, not a float. Required sections are tagged unions:
    `items_found` (≥1 item) | `none_known` (with its own quote) | `no_information`.
  - Use `extraction_output_format()` with `messages.create(output_config=...)`, not `messages.parse()`
    (the SDK transform drops descriptions). Schema ≈20 KB; compilation by the API not yet tested.
  - v1.1.0–1.1.1 (2026-10-08): D-7 `none_known_statements` in allergies `items_found`; D-9 `printed_code` /
    `printed_code_system_text` hints (cleared and flagged by `ground.py` if not in the quote); discriminated
    section unions. Prompt `extract_v2`. "None known" statements never match fuzzily in grounding.
- [x] `app/fhir/models.py`: thin Pydantic v2 models for the R4 resources/datatypes IPS uses (Bundle, Composition, Patient, AllergyIntolerance, MedicationStatement, Medication, Condition, Device, …); round-trip test against the IG examples in `tests/fixtures/ips-examples/` `[opus]`
  - snake_case attributes with camelCase aliases; `extra="forbid"`; unmodelled resources (Observation, …) kept
    as `GenericResource`. All IG 2.0.1 example Bundles round-trip exactly.
  - `app/fhir/constants.py`: values verified against the IPS 2.0.1 package. In 2.0.1 "no known …" is a SNOMED
    code (e.g. 716186003 allergies, 160245001 problems, 787481004 medications) and "no information" is
    `Composition.section.emptyReason` (list-empty-reason), not the IPS 1.x absent-unknown CodeSystem.
- [x] `extract.py`: send the normalised document to Claude with structured outputs → intermediate JSON `[opus]`
  - `app/llm/client.py` provider factory (Anthropic now; Bedrock/Vertex raise NotImplementedError). The SDK's DEBUG
    request logging (which would log documents) is blocked outside development.
  - Prompt `extract_v1.md` → v2 → v3 → `extract_v4.md` (v3+ state the eval gold-authoring rules; v4 also: text inside injected instructions or forged markup is never quoted); per-request random boundary token so a document can't forge the segment markup.
  - Structured outputs, streaming, cached system prompt, `fallbacks: "default"` on the Anthropic API, one
    append-only repair retry on schema-validation failure. Typed errors for refusal/truncation/validation.
  - Not yet verified against the real API: schema compilation, fallbacks + structured outputs together.
    Run `uv run python -m scripts.smoke_extract` (one paid call on synthetic data) once a key is set.
- [x] `ground.py`: verify each `source_quote` against the ingested text (fuzzy match tolerant of whitespace) `[opus]`
  - Ladder: exact → normalised (NFKC, dashes/quotes, case, whitespace) → relocated (page/locator corrected,
    flagged) → fuzzy (difflib ≥ 0.85, ≥ 8 chars, every number must match exactly; flagged) → not_found (dropped).
  - A section whose facts are all dropped becomes `no_information` + `section_unverified`, never "none known".
- [x] `assemble.py` + section mappers → IPS Bundle (Composition first, required sections, empty-section handling, `Composition.author` = pipeline `Device`) `[opus]`
  - `assemble(enriched, now=…) -> AssemblyResult` (Bundle + entry↔item mapping + PHI-free notes). Mappers in
    `app/fhir/{patient,device,allergies,medications,problems,composition,narrative}.py`. 14 variants validate in
    Matchbox with 0 errors and no unmatched entries (one warning: identifier type has text but no code).
  - D-7: scoped statements coded 409137002 / 429625007 / 428607008 (descendants of 716186003); left uncoded with
    a warning when they contradict a listed item.
  - D-8: resolved/inactive/remission → History of Past Illness; `not_stated` stays in Problem List (unless an
    abatement date is given).
  - Allergy `clinicalStatus` is mandatory in R4, so "not stated" becomes `active` with a warning; the reviewer
    should confirm it (Phase 3). Missing birthDate (neither stated nor derived, D-10) → `_birthDate`
    data-absent-reason (validates).
  - D-9: printed codes are never emitted, not even in narrative.
- [x] D-10 `derive.py`: birth date / sex from a valid Finnish personal identity code (HETU), after grounding, before assembly `[opus]`
  - `app/pipeline/derive.py` (pure, no logging). Results in `EnrichedIps.patient_derived` (marked `derived`, method
    `fi-hetu`, source identifier path, `recognised_by` label/format); never in the LLM layer. Flags
    `derived_from_identity_code` (confirm in review), `identity_code_conflict` (stated value kept),
    `identity_code_ambiguous` (several different codes: nothing derived). A consistent year/month-only stated
    birth date is completed from the code (`completes_stated`).
  - HETU verified 2026-10-13 (VNA 128/2010 § 2 as amended by 690/2022; dvv.fi): century signs `+`, `-`/`YXWVU`,
    `A–F`; mod-31 check; 002–899 issued, odd = male. **Sex only from 002–899**; 900–999 (temporary/test, the
    dataset's synthetic codes) give a birth date only. The gender-neutral-code bill (HE 132/2022, planned for
    2027-01-01) lapsed in Feb 2023, so parity still encodes registered sex; `SEX_FROM_PARITY` switches it off if a
    reform is enacted (such codes could not be told apart by format).
  - FHIR: plain `birthDate`/`gender` (no standard "derived" marker; no invented extension); info notes
    `birth_date_derived`/`gender_derived` and the Patient narrative say so; machine-readable trail in Provenance
    (Phase 5). Evals: `meta.json` `expected_patient` (truth from the HETU's authoring input) and metrics
    `patient_*_effective` + derived-value accuracy; gold keeps `birth_date: null`.
- [x] `validate.py`: call Matchbox `$validate` against IPS profile; return structured issues `[sonnet]`
  - **Gotcha:** a Bundle entry that fails its IPS profile doesn't match a slice, and its errors are hidden. The only
    trace is an information issue "does not match any known slice". `ValidationResult.unmatched_bundle_entries`
    exposes these, and `assemble.py` must treat them as failures. Always set `effective[x]` (use
    data-absent-reason when unknown).
- [ ] `evals/run_evals.py` with baseline metrics recorded in `evals/RESULTS.md`; deterministic normalised matching against gold, LLM judge only for unmatched leftovers `[opus]`
  - Harness built (2026-10-08): modes `gold` (self-test: all metrics 1.000, 26/26 validator pass), `cached`, `live`
    (cost estimate + confirmation + `--max-cost-usd`), `--validate`, `--judge`. Runs saved in `evals/runs/` (ignored).
  - Not ticked until a live baseline is recorded in `evals/RESULTS.md`. Estimated cost of one full live run:
    ≈ $6.3 on Opus 5.5 @ high, ≈ $3.2 on Sonnet 5.5 (pass `--max-cost-usd 8`; default is 5).

**Done when:** ≥90% of eval docs produce validator-clean Bundles (no errors); per-section recall baseline recorded.

### Phase 2 — Terminology & repair
- [x] `terminology.py`: tools `search_snomed`, `search_loinc`, `search_medication` (ATC) via FHIR `ValueSet/$expand` / `CodeSystem/$lookup` `[opus]`
  - Done 2026-10-13 as `app/terminology/` (client, scopes, tools) + `app/pipeline/terminology.py` (`code_enriched`).
    tx.fhir.org: SNOMED International (English only, so search terms must be English), LOINC, ATC
    (`http://www.whocc.no/atc`), ICD-10 WHO, EDQM. IPS ValueSets aren't hosted, so their compose is POSTed inline.
  - Deterministic pass (no LLM): printed codes looked up and kept as *candidates* (D-9); exact English
    display matches coded. For FI/SV documents this codes almost nothing without the LLM pass.
  - Privacy: only `codable_paths` term text is sent; the client rejects identifier/date-like text; httpx URL
    logging is silenced (it would log search terms).
  - Not wired into the pipeline yet.
- [x] Claude tool loop (strict tools, `tool_choice: auto`) chooses codes from candidates only `[opus]`
  - Sonnet 5.5 @ medium, prompt `terminology_v1`, strict tools, bounded per field/document/turns; chosen codes
    must have been returned by a tool in that conversation (else rejected). Tested with a fake Claude only;
    needs one real smoke call. Estimated ≈ $0.10–0.15 per document.
- [ ] `repair.py`: feed validator issues + offending intermediate item to Claude, patch intermediate JSON, re-map; max 2 loops, then flag `[opus]`
- [ ] Add sections: Immunizations, Results, Procedures, Medical Devices `[sonnet]` (follow the Phase 1 mapper pattern)
- [ ] Eval metric: code accuracy vs gold codes `[sonnet]`
- [ ] Re-run evals with cheaper per-step models (§8.1 "try" column); keep only where metrics hold `[sonnet]`

**Done when:** code accuracy measured; no hallucinated codes (every code exists in terminology server); repair loop reduces validator errors on eval set.

### Phase 3 — API + PWA MVP
- [x] API: `POST /jobs` (upload), `GET /jobs/{id}`, `GET /jobs/{id}/events` (SSE), `GET/PUT /jobs/{id}/draft`, `POST /jobs/{id}/approve`, `GET /jobs/{id}/ips` `[sonnet]`
  - Done 2026-10-13 under `/api/…` (`app/api/jobs.py`); plus `GET /api/jobs/{id}/source[/original]`. Errors carry
    no PHI; all `/api/` responses `no-store`. Drafts are versioned (stale PUT → 409).
- [x] Worker runs pipeline; status events per step `[sonnet]`
  - RQ worker (`app/worker/`), orchestrator `app/pipeline/run.py`: ingest → extract → ground → derive (D-10) →
    terminology (`TERMINOLOGY_MODE` off|deterministic|llm; a failure doesn't fail the job) → assemble → validate.
    Postgres (SQLAlchemy + Alembic; append-only `audit_events` via trigger, not yet tested live), originals in MinIO.
  - Dev-only `EXTRACTOR=replay` returns eval gold for byte-identical eval documents (no API key needed).
- [x] PWA: upload (file + mobile camera capture), progress view, review screen (sections list ↔ source viewer with highlighted `source_quote`), edit/accept/reject per item, approve, export JSON `[opus]`
  - Review screen with source highlighting (line/row/JSON path segments; PDF via pdfjs text layer — unit-tested
    only, not yet tried in a real browser). Camera capture deferred to Phase 4 (needs OCR).
  - Verified 2026-10-13 through the API: fi09 (txt), mx02 (pdf), en02 (md) → derive → terminology → review →
    confirm → approve → download; approved Bundles 0 errors, no unmatched entries; no PHI found in api/worker logs.
- [x] Approval: reviewer recorded as `Composition.attester` (`personal` for a patient, `professional` for a clinician), not as author; approval blocked until Patient name and birth date are present `[opus]`
  - Gap: a reviewer can't *add* a missing name or birth date, only edit/confirm existing facts.
- [x] Manifest, icons, installability; service worker caches app shell only `[opus]` (PHI rule — review carefully)
  - Build runs `scripts/check-sw.mjs`: only the app shell is precached and `/api/` is NetworkOnly.
- [x] Role-first flow: the app first asks patient or clinician (self-declared, kept in `sessionStorage`, not auth). Clinician gets the compact review screen; patient gets a one-question-at-a-time review with deterministic plain-language sentences (`lib/sentences.ts`) and a summary step to approve. The role chosen at the start is the attester type (the role radio in `ApprovePanel` is gone). Styling is a placeholder until the LUVN look and feel lands. Multi-document upload is not part of this (D-12). `[opus]`
  - Deviation (2026-10-13): the patient review is now one page per IPS section (about you, allergies, medications, …) with a short explainer and all of the section's fact boxes stacked. Each box has three parts: the fact (what goes into the IPS), what it means (the plain-language sentence) and the source (line number for text, whole object for JSON, whole row for CSV, page for PDF; `lib/sourceExcerpt.ts`). The final step shows the whole summary, facts only, every section included. The section explainers (`section.intro.*`) are paraphrased, patient-friendly versions of the IPS section purposes, not verbatim IPS text — check them against the IG.
- [ ] OIDC login (Keycloak dev realm) `[opus]`
  - Deviation (2026-10-13): patient name, birth date and sex show a field label in the fact box and summary. The final summary lists only facts the patient answered yes to (or changed); a section with unanswered facts shows a notice that they are left out. Backend export still includes pending facts if the patient approves with unanswered items — not changed here.
  - **Deferred:** dev-only fixed reviewer behind `APP_ENV=development` (`get_current_user` is the OIDC slot);
    the API refuses to start outside development.

**Done when:** a user can upload a PDF on a phone, watch progress, review with source highlights, approve, and download a valid IPS Bundle.

### Phase 4 — More inputs & quality
- [ ] Scanned PDFs, images/photos (multi-page capture): local OCR at ingest; DOCX, HL7 v2, CDA (deterministic parsers where structured) `[opus]`
- [x] LUVN database dump: per-patient JSON of the table rows + deterministic parser (no LLM) `[opus]`
  - 2026-10-13. `app/sources/luvn/`: `dump.py` (LUVN JSONL tables → SQLite → one dump per patient; each table is a
    property of `tables`, original column names), `parse.py` (dump → `IpsExtraction`; quotes and locators come from the
    ingested JSON leaves, so grounding is `exact`), `icd10_fi.py` (display names for the 30 codes in the data).
    `StructuredFirstExtractor` routes dumps to the parser and everything else to the configured extractor. CLI:
    `scripts/luvn_dump.py`; format and how to produce it: `app/sources/luvn/README.md`.
  - Mapped: patient (birth date, sex, ids; no name in the tables), medications (`laakitys`, ATC as printed-code hint),
    problems (`diagnoosi`, ICD-10 as printed-code hint). Allergies: `no_information`. Labs, procedures and encounters
    stay in the dump until the Results/Procedures sections exist. 1,000 sample patients: every quote grounds exactly.
  - Not validated in Matchbox yet (Docker was unavailable). The HTML IPS reader is a later task.
  - Follow-up (2026-10-13): `dump` takes filters (`--with-labs`, `--active-meds`, `--has-long-term-dx`, `--min-score`, …) and
    writes `manifest.json` (files best first, counts and an IPS score, no row contents); see the README. Of 15,000
    patients, 8,401 have an active medication, 4,849 a long-term diagnosis and 3,364 lab results.
- [ ] Multi-document merge into one IPS (future enhancement per D-12: multi-document upload, and merging several IPS summaries; dedupe meds/problems across docs; D-11: a "none known" claim contradicted by another document is not asserted and is flagged) `[fable]`
- [ ] Rendered human-readable IPS view (Composition narrative) `[sonnet]`
- [ ] Prompt caching for system prompt + schema; Batch API path for bulk backfills `[sonnet]`

### Phase 5 — Production hardening
- [ ] `Provenance` resource on every approved Bundle (pipeline Device as author, model id actually used, prompt version, reviewer as attester) `[sonnet]`
- [ ] Append-only audit log of all LLM calls and user actions `[opus]`
- [ ] EU data residency for LLM (provider per §7.1 D-5), DPA, retention policy `[opus]`
- [ ] Temporal for durable workflows; rate limiting; observability (OpenTelemetry) `[opus]`
- [ ] Optional: HL7 Europe Patient Summary / national (Kanta / FI base) profile validation `[opus]`
- [ ] Regulatory assessment: EU MDR (SaMD?), EU AI Act, DPIA `[fable]`

## 7. Open questions
- Target jurisdictions/profiles beyond base IPS (EU EPS? Finnish national profiles?)
- Hosting / LLM data-residency choice: see §7.1 D-5
- SNOMED CT licensing for target countries; Finnish medication codes (VNR/ATC) mapping
- Who are the users (clinicians, patients, admins)? Affects review UX and auth.
- Integration targets (EHR, Kanta, MyHealth@EU) and timeline

### 7.1 Decisions

| # | Decision | Status |
|---|---|---|
| D-1 | Codes fixed by the IPS IG (section LOINC codes, "no known …" codes) are allowed as **named constants in `app/fhir/` only**. All other codes come from terminology lookups; the LLM never outputs codes. | Decided 2026-10-07 |
| D-2 | Phase 1 inputs are **plaintext, JSON, CSV and text-layer PDFs**, grounded against their own text. Scans/photos and OCR come in Phase 4. | Decided 2026-10-07 |
| D-3 | Eval matching: **deterministic normalised matching first, LLM judge only for leftovers**. Other approaches if the need arises. Gold derived from Synthea records (proposal, not yet confirmed). | Decided 2026-10-07 |
| D-4 | `Composition.author` = the pipeline **`Device`** (IPS: author types determine whether a summary is "automatically generated" or "human-curated"). The reviewer, who may be the patient, is a **`Composition.attester`** (`personal` for patient, `professional` for clinician) and appears in Provenance, not as author. Approval is blocked until Patient name and birth date are present. | Decided 2026-10-07 |
| D-5 | LLM hosting: **Anthropic API for development (synthetic data only)**, behind a provider-agnostic client factory; choose **Bedrock or Vertex EU regional** before any real data (Phase 5). See §7.2. | Decided 2026-10-07 |
| D-6 | **Own thin Pydantic v2 FHIR R4 models** in `app/fhir/`; Matchbox is the conformance gate. `fhir.resources` removed (it has no R4 models on Pydantic v2). | Decided 2026-10-07 |
| D-7 | Allergies `items_found` may also carry scoped "no known …" statements (e.g. NKDA alongside a food allergy), each quoted. | Decided 2026-10-08 |
| D-8 | Resolved/inactive conditions go to the optional **History of Past Illness** section; active ones to the Problem List. | Decided 2026-10-08 |
| D-9 | Codes printed in a document (ICD-10, ATC, …) are captured as text hints only; the terminology step uses them only if the server confirms the code exists and matches the text. | Decided 2026-10-08 |
| D-10 | Birth date and sex are **derived deterministically** from a valid Finnish personal identity code (never by the LLM) when the document doesn't state them, and marked as derived for review. IPS 2.0.1 requires `Patient.birthDate` (1..1). | Decided 2026-10-13 |
| D-11 | "Allergiat: ei tiedossa" (bare "not known") is `none_known` (scope all) with its source quote when no other document says anything about allergies. If another document suggests allergies (Phase 4 merge), the "none known" claim is not asserted: the section becomes `no_information` and is flagged for review. | Decided 2026-10-13 |
| D-12 | **One document → one summary** stays the design for now (one job = one document = one IPS). Possible future enhancements, not scheduled: (a) uploading several documents and reviewing them together as one job (needs cross-document dedupe, conflict flagging and a same-patient check); (b) merging several existing IPS summaries into one. Both build on the Phase 4 merge task and D-11. | Decided 2026-10-13 |
| D-13 | The PWA uses the **LUVN look and feel** (palette, Verdana type, 0.5rem radii, gray header, 4px focus rings) for a possible LUVN-run front end, defined as CSS custom properties in `frontend/src/index.css`. No LUVN logo, icons or photos. | Decided 2026-10-13 |

Still open, before the phase that needs them:
- ~~Phase 1 validity without codes~~ **Resolved:** text-only `CodeableConcept`s give 0 errors and no extra warnings in IPS 2.0.1 (bindings are "preferred"). Fixtures in `tests/fixtures/ips-variants/`.
- **FI/SV terminology search (Phase 2).** `tx.fhir.org` searches English terms. The terminology loop must search with English terms (translated by Claude) while keeping the original-language `source_quote`.
- **Audit log vs. "never log PHI" (Phase 5).** The audit log of LLM calls contains PHI. Define it as an encrypted, access-controlled store, separate from application logs.
- **Queue:** RQ unless someone objects before Phase 3.

### 7.2 D-5: hosting, cost and capability (as of 2026-10-07)
- **Anthropic API:** list prices (§8.1). `inference_geo` offers only `global` or `us` (+10%), and workspace data storage is US-only. **No EU inference option**, so it is fine for synthetic-data development, but likely unsuitable for real Finnish/EU PHI.
- **Amazon Bedrock / Google Vertex, EU regional endpoint:** **+10%** over their global endpoints; base prices set by AWS/Google. Missing compared with the Anthropic API: Anthropic's Message Batches API (50% off; use the platform's own batch offering instead), server-side refusal `fallbacks` (use the SDK's client-side fallback middleware), Files API, `inference_geo`.
- **Cost scale:** the region premium is about 10%. Model choice per step is a 2–40× lever, so it matters far more.
- **Decision:** develop on the Anthropic API now (synthetic data only), behind a provider-agnostic client factory in `app/llm/client.py`. Choose Bedrock or Vertex EU before any real data, based on existing cloud contracts and DPA.

## 8. Model selection

### 8.1 Runtime: which model each pipeline step calls
Set in `app/llm/models.py`. Start every step on the **Start** model; move to **Try** only after evals show
no regression (Phase 2 task). Prices are per 1M tokens, input/output.

| Step | Start | Effort | Try (cheaper) | Why |
|---|---|---|---|---|
| 2. Classify & route | `claude-sonnet-5-5` | `low` | `claude-haiku-5-5` | Short output, easy task. |
| 3. Extraction | `claude-opus-5-5` | `high` | `claude-sonnet-5-5` @ `high` | Core quality driver; long multilingual documents. |
| 5. Terminology tool loop | `claude-sonnet-5-5` | `medium` | `claude-haiku-5-5` | Picks among server candidates; many calls per doc. |
| 7. Repair | `claude-opus-5-5` | `medium` | — | Rare, hard (validator messages → schema fix). |
| 4b. Multi-doc merge (Phase 4) | `claude-opus-5-5` | `high` | — | Clinical dedupe judgement. |
| Evals: LLM judge for item matching | `claude-sonnet-5-5` | `medium` | — | Use a different model from the one being judged where possible. |
| Dev only: synthetic eval doc generation | `claude-opus-5-5` | `high` | — | Realistic, messy FI/SV/EN documents in all Phase 1 formats. |
| Bulk backfill | same as step 3 | same | — | Use batch processing (50% off on the Anthropic API; see §7.2 for Bedrock/Vertex), not a cheaper model. |

Pricing (Anthropic API list price): Opus 5.5 $4/$20 · Sonnet 5.5 $2/$10 · Haiku 5.5 $0.10/$0.50 (≤100K-token prompts; $0.50/$2.50 above) · Fable 5.1 $10/$50.
All four have 1M context and adaptive thinking with `effort`. Haiku 5.5 replaces Haiku 4.5 as the cheap option (about a tenth of the price, newer API surface).

Rough, unmeasured estimate for extraction on Opus 5.5 @ `high`: about $0.30–0.50 per 10-page document, dominated by output and thinking tokens; Sonnet 5.5 is about half. Replace with measured numbers from the Phase 1 evals.
**Not using `claude-fable-5-1` at runtime:** 2.5× Opus cost, and it requires 30-day data retention
(no zero-data-retention), which conflicts with PHI handling. At most, a one-off eval ceiling on synthetic data.

API notes for implementers (current models):
- Opus 5.5 **defaults to `effort: medium`**; always set `output_config.effort` explicitly. Thinking can't be disabled; lower effort instead.
- Forced `tool_choice` (`any`/`tool`) returns 400 on Opus 5.5 / Sonnet 5.5; use `auto` + `strict: true` tools (as planned).
- PDF **citations are incompatible with structured outputs**, so `source_quote` must stay a schema field checked by `ground.py`.
- Handle `stop_reason == "refusal"` (medical text can hit safety classifiers). Use server-side `fallbacks` on the Anthropic API, or the SDK's client-side fallback middleware on Bedrock/Vertex; record the model actually used in Provenance.
- Keep tool/repair loop histories append-only (thinking blocks are bound to the conversation).
- Prompt caches are per model; changing a step's model resets its cache.
- Data residency: see §7.2 (`inference_geo` has no EU option; EU means a Bedrock/Vertex EU regional endpoint).

### 8.2 Development: which Claude Code model to use per task
Switch with `/model` before starting a task. Tags in §6:

| Tag | Model | Use for |
|---|---|---|
| `[sonnet]` | Sonnet 5.5 | Scaffolding, CRUD endpoints, config, CI, tasks that copy an existing pattern. |
| `[opus]` | Opus 5.5 (default) | Most feature work: pipeline steps, LLM integration, PWA review UI, security-sensitive code. |
| `[fable]` | Fable 5.1 | Few high-leverage design tasks where mistakes spread: intermediate schema, multi-doc merge, regulatory analysis. Synthetic data only in prompts. |

If unsure, use `[opus]`. A task's tag is a starting point; switch up if the model struggles.
