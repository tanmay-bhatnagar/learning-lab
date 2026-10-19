# Per-query diagnostic traces

Trace logging records how a chat request ran so development work can investigate latency, retrieval, failures, and cancellation. It is separate from the [retrieval evaluation suite](../evals/retrieval/README.md). There is no external telemetry service or new learner-facing screen.

## Scope and persistence

Every valid chat request whose topic resolves safely gets a trace, including busy-topic and other preflight rejections. Both Default/legacy and named conversation routes use the same instrumentation. Malformed request bodies, missing or unsafe topics, and middleware rejections happen before this boundary and do not create a topic trace.

Records live in the topic's flat `query_traces.sqlite`, separate from the retrieval index and saved histories. Version 1 is additive; existing JSON conversations and original PDFs retain their formats. Reads and writes use the existing validated topic paths. Unsupported or corrupt trace storage fails visibly.

The request is first recorded as `started`, then finalized as `completed`, `rejected`, `error`, or `cancelled`. Completion means both model completion and successful answer persistence. Disconnect after durable completion does not change that outcome. A process crash can leave a `started` record; it remains visibly unfinished rather than being assigned an invented result.

## Metadata

Traces contain request/topic/conversation identifiers, saved message positions, UTC timestamps, requested model and reasoning/context settings, retrieval settings and evidence identifiers, context usage, output character counts, timings, outcome, sanitized error categories, and persistence flags. They do not duplicate question, prompt, answer, thinking, document passages, or images. Stream fragments and characters are not token counts.

Elapsed times use a monotonic clock. Retrieval time includes waits for embedding inference; generation time includes model queueing and provider work. First output means the first thinking or answer fragment. These route-level timings are not GPU-only or provider-only execution measurements.

Trace initialization must succeed before history mutation or model work. A final trace-write failure preserves an already saved answer, releases the topic lock, reports a diagnostic stream failure where connected, and records a sanitized server error. It is not automatically retried; an existing `started` row remains honestly unfinished. Trace logging cannot guarantee successful persistence when its own storage is unavailable.

## Developer inspection

The API exposes a bounded, newest-first topic trace list, optionally filtered to a validated conversation. It provides no cross-topic aggregation. Exact endpoint and record fields are specified in [API.md](API.md).

The implementation and verification use synthetic topic roots. Regression checks cover successful turns, retained evidence, rejection, cancellation, model failures, trace/history persistence faults, and topic/path isolation. The separate retrieval suite adds source-checked gold questions, anchor recall and reciprocal rank, and verifies these traces against actual retrieval and retained evidence. Model-quality judgments remain unassessed.

## Validation — 3 October 2026

The final backend passed 243 tests and 21 subtests. The frontend passed 90 tests and its production build. Engineering checks, Ruff, Python formatting, ESLint, Prettier, and `git diff --check` passed. Independent review found no remaining confirmed actionable findings after fixes for lifecycle, storage, and final-write failures. Sources: `services/api/tests/test_query_traces.py`, the existing chat regression tests, and local evidence below.

An isolated real Docling/Ollama run retrieved a synthetic PDF with hybrid search; the installed Qwen model answered 42. Trace evidence identifiers, page, rank, and score matched the saved citation. Browser Stop produced a cancelled trace linked to the incomplete saved answer, with matching output character count. Conversation filtering returned only that conversation's traces. A subsequent real-model smoke confirmed successful completion and the version-1 database schema. Sources: the usage notes below.

Evidence is retained under ignored `.local/verification/`:

- `trace-20261003/review.md`: independent review, cancellation matrix, metadata/privacy probes, schema refusal, and persistence-fault checks.
- `trace-20261003/backend-final.log`, `test-final.log`, and `build-final.log`: automated gates.
- `20261003-031254-1a290580/trace-usage-notes.md`: real parser/model retrieval and browser cancellation.
- `20261003-031807-b7db45c3/trace-schema-smoke.md`: subsequent real-model schema smoke.
- `20261003-031258-33dfaa52/evidence.json`: isolated HTTP conversion/persistence verification.

The browser run preceded the final storage fault-handling changes; those changes were covered by automated regressions and independent review. Browser automation could not operate the file chooser, so upload used the real multipart API. This verifies lifecycle and metadata behavior on synthetic inputs, not retrieval quality across a gold corpus, parser fidelity, multiprocess writers, or power-loss recovery. Owned verification services and the browser tab were closed. No personal topics, model downloads, commits, or publication were involved.

## Optional answer-or-search metadata

Opted-in chat adds the optional version1 `evidence_search` object described in [API.md](API.md#optional-extra-document-search). The database stays version1; older records remain readable. Initial, returned, novel and final retained source identities are separate, as are declared labels and all supplied citations. Counts measure application gateway/lookup invocation attempts. A prepared prompt is not marked supplied until gateway iterator construction succeeds; no counter proves provider receipt or semantic use. Cancelled/error records preserve the last known workflow stage and sanitized code. Initial and additional retrieval time accumulates in milliseconds. Generation time includes the bounded decision/search/final workflow, not only model inference; first output excludes suppressed planning content and progress notices. Canonical warnings exclude raw generated queries/CV/provider text. Actual model/browser validation remains separately recorded in dated feature notes.
