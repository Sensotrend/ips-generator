# CLAUDE.md

Healthcare document → International Patient Summary (IPS, FHIR R4) extraction pipeline with a React PWA.

**Read `PLAN.md` before starting work.** It holds the architecture, key decisions (D1–D8, plus D-1–D-6 in §7.1),
and phased task list. Work on the current phase, tick completed tasks, and note any deviation under the task.

## Non-negotiable rules
- The LLM fills the intermediate schema in `backend/app/schemas/intermediate.py`; FHIR is built only by
  deterministic mappers in `backend/app/fhir/`. Never have the LLM emit FHIR resources directly.
- Never invent clinical codes. Codes must come from terminology-server lookups; otherwise keep text only.
  Only exception: codes fixed by the IPS IG (section codes, "no known …" codes) as named constants in
  `backend/app/fhir/`. The LLM never outputs codes; it may only copy a code printed in the document into a
  `printed_code` hint field, which is used only as a terminology search hint (PLAN D-9).
- Every extracted fact keeps `source_quote` and `page`.
- No real patient data in the repo, fixtures, logs, or prompts. Use Synthea / synthetic documents.
- Never log document contents or PHI. Never cache PHI in the PWA service worker.
- Secrets come from environment variables; never commit `.env`.

## Stack & conventions
- Backend: Python 3.12, FastAPI, Pydantic v2, own FHIR R4 models in `backend/app/fhir/`
  (no `fhir.resources`), official `anthropic` SDK. Models are set per
  pipeline step in `backend/app/llm/models.py` (see PLAN.md §8.1); never hardcode a model id elsewhere.
  Tooling: uv, ruff, mypy, pytest.
- Frontend: React + TypeScript + Vite + `vite-plugin-pwa`, TanStack Query.
- Local services: `docker compose -f infra/docker-compose.yml up`.
- Prompts live as versioned files in `backend/app/llm/prompts/`; bump the version when changing one.

## Definition of done for pipeline changes
- Unit tests pass (`pytest`), mappers covered by tests.
- Generated Bundles validate against the IPS IG in Matchbox with no errors.
- Run `evals/run_evals.py` for extraction/prompt changes and record results in `evals/RESULTS.md`.
