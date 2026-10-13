# IPS Generator

Turn arbitrary healthcare documents into a valid **International Patient Summary (IPS)**: a FHIR R4
document Bundle conforming to the [HL7 IPS IG](https://hl7.org/fhir/uv/ips/) (`hl7.fhir.uv.ips#2.0.1`).
A human reviews and approves every result in a mobile-friendly PWA.

> **Status: Phase 1 in progress.** The extraction pipeline (ingest → extract → ground → assemble →
> validate) and the eval harness exist as a library and CLI. The HTTP API only exposes `GET /health`,
> and the PWA is a scaffold. Job endpoints, the review UI, terminology coding and the repair loop come
> in Phases 2–3. See [PLAN.md](PLAN.md) for the roadmap and decisions.

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
PWA (React + Vite)            upload → progress → review & edit → approve → export     [scaffold]
        │
API (FastAPI)                 jobs, SSE status, review, audit                          [/health only]
        │
Pipeline (backend/app/pipeline)
  1. ingest      normalise to located text segments (line / row / JSON path / page)    [done]
  2. classify    document type, language, relevant sections                            [planned]
  3. extract     Claude, structured outputs → intermediate JSON                        [done]
  4. ground      check each source_quote against the source text                       [done]
  5. terminology Claude tool loop over a FHIR terminology server                       [planned]
  6. assemble    deterministic mappers → IPS document Bundle                           [done]
  7. validate    Matchbox $validate (IPS IG); targeted repair of the JSON, not FHIR    [validate done]
  8. review      human approval → Provenance → FHIR server                             [planned]
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

```sh
cd backend  && uv run uvicorn app.main:app --reload     # http://localhost:8000/health
cd frontend && npm run dev                              # Vite dev server
```

Only `/health` exists so far. The upload and review flow arrives in Phase 3.

### Run the pipeline

Until the job API exists, use the pipeline modules directly. For one paid smoke test of extraction on
a synthetic Finnish discharge summary:

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

## Definition of done for pipeline changes

- `pytest` passes and the mappers are covered by tests.
- Generated Bundles validate against the IPS IG in Matchbox with no errors.
- For extraction or prompt changes, run the evals and record the result in `evals/RESULTS.md`.

## Further reading

- [PLAN.md](PLAN.md): architecture, decisions (D1–D8, D-1–D-11), model selection, phased task list
- [CLAUDE.md](CLAUDE.md): project rules for contributors and coding agents
