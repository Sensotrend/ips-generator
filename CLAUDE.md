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
- Frontend languages: English, Finnish, Swedish (`frontend/src/locales/{en,fi,sv}.ts`, helpers in
  `frontend/src/lib/i18n.ts`). No user-visible string is hardcoded in a component: add it to `en.ts`
  and to `fi.ts` and `sv.ts`, and use `t(...)`. **Whenever you change the frontend, check the
  translations:** new or reworded English text needs matching Finnish and Swedish, and removed text
  must be removed from all three catalogues. `lib/i18n.test.ts` checks the keys and placeholders but
  not the wording, so re-read the fi/sv text you touched. **When you change fi/sv text, end your report
  with clickable links to `fi.ts` and `sv.ts` in the current worktree** (so the reviewer can read them
  in context); for small changes also show the new strings as a table (key, EN, FI, SV).
- Local services: `docker compose -f infra/docker-compose.yml up`.
- Prompts live as versioned files in `backend/app/llm/prompts/`; bump the version when changing one.

## Definition of done for pipeline changes
- Unit tests pass (`pytest`), mappers covered by tests.
- Generated Bundles validate against the IPS IG in Matchbox with no errors.
- Frontend changes: `npm run typecheck`, `npm run lint`, `npm test` pass, and translations are checked
  (see Stack & conventions).
- Run `evals/run_evals.py` for extraction/prompt changes and record results in `evals/RESULTS.md`.

## Git workflow (parallel chats and agents)
Full conventions are in the README, "Git workflow". Rules for Claude:
- One chat = one worktree = one branch (`<initials>/<topic>`), created from a fresh `origin/main`. Use
  `claude --worktree`; subagents that write code use `isolation: "worktree"`. Never work on `main` in a
  checkout another chat may be using. This applies to every change, including docs (CLAUDE.md, README,
  PLAN.md) and config: no edits directly in the main checkout.
- At the start of a task: `git fetch --prune origin`, check whether `main` moved, and look at
  `git branch -r --no-merged origin/main` to see what the other developer is doing. Base work on
  `origin/main` only.
- Commit and push only when the user asks or the task says so. When pushing is in scope, push the branch
  at least hourly. Landing on `main` is allowed without a PR: rebase on `origin/main`, run the tests,
  `git push origin HEAD:main`. Linear history only: no merge commits, never force-push `main`;
  `--force-with-lease` only on your own branch.
- Never run `git stash`, `reset --hard`, `clean` or `checkout .` on a tree you did not create, and never
  delete branches or worktrees you did not create. If you find uncommitted changes you did not make, stop
  and ask.
- Review commands from the user (details in README, "Git workflow"): **"test branch"** = run API, worker
  and PWA from this worktree (reuse unaffected Compose services) and give the localhost link; **"push
  branch"** = push this branch to `origin`; **"approved"** = rebase on `origin/main`, test, fast-forward
  push to `main`, fast-forward the main checkout (`git -C <main checkout> merge --ff-only origin/main`;
  skip and tell the user if it has uncommitted tracked changes), then delete the remote branch, local branch and worktree (stop on conflict or test
  failure). When a piece of work is finished, ask which of the three the user wants.
- Subagents leave their work on their own branch and report back; they do not push to `main`.
