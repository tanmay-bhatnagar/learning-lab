# Initial R1 foundation validation — 10 September 2026

Environment: macOS on M3 Pro, 36 GB unified memory, Python 3.13.3, Node 25.2.1, Ollama 0.33.3. Exact Python package versions are in `../services/api/requirements-macos-py313.lock`; browser packages are in `../apps/web/package-lock.json`.

## Passed

- 54 backend/model/context tests plus 13 parameterized subtests: topic persistence, immutable uploads, path and symlink rejection, cross-topic file rejection, untrusted browser origins/hosts, upload size limits, parser failures, partial chat retention, local/cloud model validation, thinking capabilities, stream parsing, oldest-input truncation, protected system messages, preserved attachment suffixes, and response-budget cutoff reporting.
- Four browser-client stream tests: split NDJSON, premature EOF, server errors, HTTP errors.
- TypeScript checking and Vite production build.
- `pip check`: no broken dependencies.
- Real synthetic PDF converted by both MarkItDown 0.1.7 and firecrawl-anydoc 0.2.4; extracted calibration value verified; original PDF bytes unchanged.
- Real streamed PDF-grounded answers from `qwen3.5:4b-q8_0` and `qwen3.5:9b-q4_K_M`, with thinking disabled. Saved history and runtime context counts verified.
- Browser workflow in a separate temporary Learning root: create topic, upload via anydoc, inspect Markdown and original PDF viewer, explicitly select the attachment, save Qwen configuration with thinking enabled, receive thinking and final answer, see measured usage (2,166 / 8,192 in that run), reload saved conversation.
- Narrow-panel and desktop layouts inspected.

Downloaded local candidates: Qwen3.5 4B Q8 (5.28 GB download) and 9B Q4_K_M (6.59 GB download). Existing Gemma3 12B and DeepSeek R1 14B were discovered; this pass did not benchmark their generation. Qwen4 was observed using GPU inference in Ollama. This is functional validation, not a latency/quality or maximum-memory benchmark.

## Limits

Only a small synthetic, text-based PDF was used for integration checks. Parser quality on equations, complex tables, scanned pages and long real documents remains to be compared. No personal evidence was used for tests. Personal Learning folders remain unpopulated.

Reasoning can be verbose on small models. A generation-budget cutoff now reports an incomplete response and preserves partial output. The context meter reflects the latest request; preflight budgeting uses conservative estimates, not an exact tokenizer. No summarization or compaction exists.

This build is the local app/ingestion foundation. Full R1 retrieval, LangGraph learning tools and learning-progress workflows remain later increments. Model-executed tools, coding execution, external research, multimodal input and Jetson serving are not enabled.

## 3 October 2026 updates

The multi-conversation increment and its repairs are recorded in [resume validation](../conversations/2026_10_03_resume_validation.md). Per-query diagnostic trace logging is implemented and independently reviewed; its contract, final automated gates, real-model checks, and coverage limits are recorded in [query traces](../../query_traces.md). The separate [retrieval evaluation suite](../../../evals/retrieval/README.md) is implemented; it evaluates registered public PDFs in isolated workspaces with simulated generation.

The three-paper developer baseline and final automated gates are recorded in [retrieval eval validation](../retrieval-evaluation/retrieval_eval_validation.md). Scores remain descriptive; answer quality is unassessed.

## 5 October 2026 — checkpoint policy and local commit baseline

Recorded the existing local application work in scoped `dev` commits and required frequent checkpoint commits in Code-root AGENTS.md, all six development skills/configs, both parser-reference skills, engineering conventions, repository guidance, review checklist, and task handoff. Failing intermediate tests do not block local checkpoints; completion gates and separate remote-push authorization remain.

Fresh complete-working-tree `make test` passed 282 backend tests plus 21 subtests and 90 web tests; `make build`, engineering checker, Ruff, Python formatting, ESLint, Prettier, and six development-skill validations passed. Intermediate commits were not tested independently. Tests/build logs remain ignored under `.local/checkpoint-tests-20261005.log` and `.local/checkpoint-build-20261005.log`. No browser, real-model/parser, or isolated HTTP rerun; no push, merge, or release.
