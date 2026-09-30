# R1 ingestion and retrieval refactor — Claude handoff

Status: **implemented and automated checks passed** (30 September 2026). Base: `dev` at `13ca810` (application code landed in `b2a6b71`). This is the original scope and acceptance record for the refactor. A single Code subagent implemented it at Tanmay's request. The coordinator then updated tests and ran 128 Python tests, 17 frontend tests, and the web build. Live Ollama and browser use remain unverified.

Follow-up (1 October 2026): the architecture review found that item 4 had regressed "keyword retrieval still works when embeddings are unavailable": a missing embedding model raised `ValueError`, which the narrowed catch did not handle. Commit `b3a54e6` fixed this with `EmbeddingUnavailable` and was verified live. Item 3's app-lifetime model lock is in place. Items 1 and 2 are partly done; see [architecture-review.md](architecture-review.md).

## Objective

Make the existing PDF ingestion → chunking → indexing → retrieval → cited chat path easier to reason about and extend. This is a **behavior-preserving** pass after the five reviewed bug fixes. Keep it limited to the backend path; do not add R1 features.

## Current flow

`PDF upload → Docling parse → bounded chunks and assets → topic SQLite index → ranked evidence → prompt budgeting → Ollama stream → answer with persistent citations`

MarkItDown and AnyDoc provide unindexed Markdown fallback. All learning data belongs in one explicit `Learning/<topic>/` outside this Git repo. The model has no shell, browser, web or hardware tools.

## Work items, in order

1. **Clarify data contracts.** Replace the most consequential `dict[str, Any]` exchanges among [parse_pipeline.py](../../services/api/lab/parse_pipeline.py), [chunking.py](../../services/api/lab/chunking.py), [index.py](../../services/api/lab/index.py), and [retrieval.py](../../services/api/lab/retrieval.py) with a small set of typed records or validated boundaries. Cover parsed artifact metadata, indexed chunks, retrieval hits and citations. Keep JSON/SQLite representations compatible; do not create a generic framework.
2. **Separate decisions from effects.** Extract record construction and ranking/trace calculations into testable functions. Keep file writes in the parse/storage boundary and SQL in the index boundary. Preserve caller-owned inputs; avoid wrappers that only forward calls.
3. **Make dependencies and resource ownership explicit.** Keep one resolved tokenizer for an ingestion operation. Give model-generation serialization a clear app-lifetime owner instead of the module-global `_GENERATION_LOCK` in [models.py](../../services/api/lab/models.py), **without allowing concurrent models to exhaust memory**. Pass clocks/settings/capabilities where decisions need them; do not introduce a service-object hierarchy.
4. **Narrow errors.** In [retrieval.py](../../services/api/lab/retrieval.py), degrade only for expected embedding outages and report that degradation. Let programming/data-contract failures surface. Correct the multi-file “atomic” claim in [parse_pipeline.py](../../services/api/lab/parse_pipeline.py): individual writes are atomic, the whole artifact set is not transactional.
5. **Update affected callers and docs.** Keep [main.py](../../services/api/lab/main.py), [models.py](../../services/api/lab/models.py), tests, and [architecture.md](../../docs/architecture.md) aligned with any internal contract changes. Use useful docstrings and minimal inline comments.

Several focused commits are fine within this single refactor. Do not mix in a new feature, storage migration, parser swap or frontend redesign.

## Behavior that must remain intact

- Originals never change; topic/path checks and cross-topic isolation remain enforced.
- Docling remains the default structured parser. Markdown alternatives still work.
- Chunk limits include the embedding prefix and special tokens; oversized chunks and captions split without changing source whitespace. An oversized heading fails explicitly. Approximate tokenizer fallback stays labelled approximate.
- An indexed selection with missing `retrieval.sqlite` fails visibly. Keyword retrieval still works when embeddings are unavailable.
- The final prompt contains whole retained evidence passages; citations match those passages. Higher-ranked passages survive tight context first. The full saved conversation is untouched by request trimming.
- Model selection, thinking controls, response streaming, and bounded memory use retain current behavior. Stored JSON and SQLite formats remain readable without a migration.

## Acceptance checks

- Add or adjust **only tests that protect a changed boundary or a listed invariant**. Existing behavior tests must remain meaningful; do not weaken them to fit the refactor.
- Run `make test`, `make build`, `.venv/bin/python -m ruff check .`, `.venv/bin/python scripts/check_engineering.py`, and `git diff --check`.
- Run `.venv/bin/python scripts/verify_workspace.py` with its isolated synthetic topic to confirm upload, conversion and original preservation. If Docling models are installed, run one isolated structured-PDF smoke as well; report if unavailable. Do not use a personal topic.
- Inspect the final diff for accidental format changes, model weights, credentials and unrelated files. Report changed boundaries, verification results, remaining risks and any observed behavior change.

The last established baseline was **128 Python tests, 17 frontend tests, passing web build, and passing CI** for `b2a6b71`; the later `13ca810` commit changed only docs. Confirm the baseline in the checkout before relying on those counts.

## Out of scope

LangGraph/tools, learning goals, document map, understanding checks, multi-session memory, context compaction, coding experiments, web research, Jetson serving, and the 107-PDF parser comparison. Tanmay explicitly deferred the full corpus comparison until he asks for it. Do not push, merge or release unless he authorizes that action for this pass.
