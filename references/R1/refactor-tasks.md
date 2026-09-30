# R1 architecture refactor — task briefs

**Status: ready, not started. Do not begin any slice until Tanmay explicitly says to start.** Starting approves this plan for the purposes of `AGENTS.md`. The coordinator may then start roles for the slices below without asking again. It still stops for anything outside this plan: new features, stored-format changes, `main`, releases, or personal topics.

Source of findings and acceptance criteria: [architecture-review.md](architecture-review.md) section 7. Phase 0 decisions and Phase 1 defect fixes are complete. This file adds what each slice needs to be executed and tracked.

## Baseline

- Branch `dev`; the base is the commit that adds this file. Confirm with `git log -1` before starting.
- Checks: 148 Python tests, 19 frontend tests, the web build, Ruff, `check_engineering.py`, and GitHub CI on `dev`, all passing.
- Decisions:
  - Prettier, ESLint (`react-hooks`) and Vitest with Testing Library;
  - `zod` validation at the browser boundary;
  - formatting only, with no size or complexity limits;
  - interrupted uploads are marked on read;
  - the coordinator may start any role within this plan.

## Rules for every slice

- Behavior-preserving. `docs/API.md` and the stored JSON/SQLite formats stay frozen. A slice that seems to need a contract or format change stops and reports to the coordinator.
- Characterization tests land before the code they protect, and later slices must not weaken them. Mechanical changes (formatting, file moves) get their own commits, checked with `git diff -w` or `git diff -M`.
- One writer per path. The frontend track owns `apps/web/`. The backend track owns `services/api/`, `scripts/` and `tests/`. Shared docs (`docs/*`, `AGENTS.md`, `.agents/`) belong to the coordinator unless a slice lists them.
- Parallel tracks run in isolated worktrees branched from `dev`. The coordinator reviews each finished slice, merges it into `dev`, reruns the checks and pushes. Nothing goes to `main`.
- Install new dependencies with the package manager at their latest versions when the slice needs them (Prettier, ESLint and plugins, Vitest, Testing Library, jsdom, `zod`). Commit the lockfile changes.
- Synthetic fixtures and temporary roots only. Never read or drive `Learning/`.
- Every slice runs `.venv/bin/python scripts/check_engineering.py`, `.venv/bin/ruff check .`, `make test`, `make build` and `git diff --check`. Slice-specific checks are listed below.

## Roles and models

The coordinator integrates and owns final verification. Code slices use the code role, and Composer is acceptable for them. Characterization and review use roles that are not Composer: debug or review on Opus 5.5 High, or the coordinator itself. If the harness substitutes Composer for an audit role, the coordinator runs that step locally instead. Each slice ends with a review of its diff against [engineering.md](../../docs/engineering.md) and the [review checklist](../../.agents/skills/review/references/checklist.md) before the merge.

## Order

```text
Phase 2 (sequential, coordinator):  G-2 → G-3 → G-4 → G-1 → G-5 → G-6
Phase 3 frontend track:             FE-0 → FE-1 → FE-2 → FE-3 → FE-4
Phase 4 backend track:              BE-0 → BE-1 → BE-2 → BE-3 → BE-4 → {BE-5, BE-6, BE-7} → BE-8
```

Phases 3 and 4 start only after Phase 2 is merged, and then run in parallel. G-2 and G-3 run first because the mechanical reformatting makes every later diff reviewable.

## Tracker

| Slice | Role | Depends on | Extra checks and evidence | Done signal | Status |
| --- | --- | --- | --- | --- | --- |
| G-2 Python format | code | — | `git diff -w` is empty apart from formatting; the test count is unchanged | `ruff format --check .` passes in CI | not started |
| G-3 TS format and lint | code | G-2 | The Prettier commit is separate from the config commit; `npm run lint` passes, with any pre-existing violations listed in the config | CI runs the format check and lint | not started |
| G-4 Vitest harness | code | G-3 | All 19 tests ported with the same intent; a test value-imports a second module | `npm test` runs Vitest; the `data:` loader is removed | not started |
| G-1 Python lint rules | code | G-2 | Every per-file ignore names today's offenders | Ruff runs `BLE001, A001, B, ANN001/ANN201` on `lab/` | not started |
| G-5 structural checks | code | G-1 | A test for each new check in `tests/` | `check_engineering.py` fails on a seeded violation | not started |
| G-6 conventions | coordinator | G-3, G-4 | Links resolve (`check_engineering.py`) | `engineering.md` has frontend, error, configuration, test-seam and refactor-procedure sections | not started |
| FE-0 characterization | debug or review | Phase 2 | The flows listed in the review pass on the current code. Record current "Refresh files" behavior and ask Tanmay whether it is intended | New tests pass before any `src/` change | not started |
| FE-1 pure extraction | code | FE-0 | Unit tests for each pure module; the dead code in the review list is removed | `main.tsx` has no stream-folding or file-status logic | not started |
| FE-2 hooks own effects | code | FE-1 | FE-0 unchanged and passing | `App` has no `fetch`, `localStorage` or `window` calls | not started |
| FE-3 components | code | FE-2 | FE-0 unchanged and passing; one `VisualAssets` | `main.tsx` only calls `createRoot` | not started |
| FE-4 zod boundary | code | FE-3 | Tests for malformed responses and stream events | No `as T` casts on responses or stream JSON | not started |
| FE exit | usage | FE-4 | A browser run of the [usage flows](../../.agents/skills/usage/references/flows.md) on an isolated root, with evidence under `.local/verification/` | Tanmay's go-ahead to close the track | not started |
| BE-0 characterization | debug or review | Phase 2 | Shared `tests/fakes.py` uses the production gateway signature | The tests listed in the review pass on the current code | not started |
| BE-1 error taxonomy | code | BE-0 | Status codes and messages are identical (compared by test) | No `fastapi` import outside the HTTP layer; `IndexError` renamed | not started |
| BE-2 contracts | code | BE-1 | JSON written by the new types matches fixtures from the current code | `ANN` ignores for `lab/` removed | not started |
| BE-3 configuration | code | BE-2 | `import lab.main` creates no app; `make dev` and `verify_workspace.py` still work | One frozen `AppConfig`; no `os.environ` outside it | not started |
| BE-4 split `main.py` | code | BE-3 | A pure `build_chat_prompt` with direct tests; no test-only branches | Routers only call domain functions | not started |
| BE-5 ingestion | code | BE-4 | Chunk JSONL is byte-identical on the synthetic fixture; a Docling smoke if models are installed | Structured warnings replace substring matching | not started |
| BE-6 retrieval | code | BE-4 | Retrieval-trace output is unchanged for the fixtures | An explicit fallback flag; the index is checked before embedding | not started |
| BE-7 model adapter | code | BE-4 | Payload and think tests are pure; a live Ollama smoke on an isolated root | One owner for the context budget | not started |
| BE-8 hygiene | code | BE-5, BE-6, BE-7 | One backend test root; no `sys.path` hacks | `architecture.md` ownership table rewritten | not started |
| BE exit | usage | BE-8 | `verify_workspace.py`, a Docling smoke and a live chat on an isolated root | Tanmay's go-ahead to close the track | not started |

## Per-slice handoff

When a slice is assigned, the coordinator fills in [docs/task-template.md](../../docs/task-template.md) under ignored `.local/refactor/<slice>.md`. The goal and acceptance come from the review, and paths, dependencies and checks come from this tracker. When the slice merges, the coordinator updates its status here in the same commit, along with the commit hash.
