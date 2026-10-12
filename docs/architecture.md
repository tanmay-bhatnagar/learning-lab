# Architecture and ownership

Current state on `dev` as of 13 October 2026. See the [interactive R1 map](../references/R1/system-map.html) for the system and its planned blocks, and the [R1 snapshot](../references/R1/README.md) for validation and remaining work.

## Runtime path

`Browser → topic API → topic-scoped retrieval → local Ollama model → streamed answer with saved citations`

A PDF upload follows a separate path: `browser → topic API → parser → bounded chunks and assets → topic SQLite index`. Selected MarkItDown and AnyDoc files use their Markdown as an unindexed chat attachment. Docling is the default structured parser.

The API app owns one model-generation lock shared by embedding, chat, section-summary and prerequisite generation, keeping local model use serialized for bounded memory. Parsed artifact writes are atomic per file; the complete set of derived files is not transactional, and a failed parse can leave partial derived artifacts.

| Location | Owns |
| --- | --- |
| `apps/web/src/main.tsx`, `App.tsx` | Vite entry (`createRoot` only) and the workspace composition root |
| `apps/web/src/api/` | Wire schemas (zod), URL builders, fetch and stream client |
| `apps/web/src/hooks/` | Side effects: bootstrap, topic session, chat, uploads, settings, preview, window events |
| `apps/web/src/state/`, `domain/` | Pure activity, topic-session and stream transitions; pure display rules |
| `apps/web/src/components/` | Presentational UI: sidebar, workspace tabs, chat, files, settings, modals |
| `apps/web/src/citations.tsx`, `retrievalTrace.tsx` | Per-answer source display and retrieval inspection |
| `services/api/lab/web/` | HTTP routers, middleware, request schemas and app factory |
| `services/api/lab/config.py` | Frozen `AppConfig` and environment defaults |
| `services/api/lab/runtime_policy.py` | Request-boundary reading and validation of the configured learning-agent policy |
| `services/api/lab/errors.py` | Domain error taxonomy |
| `services/api/lab/contracts.py` | Typed records and gateway/store protocols |
| `services/api/lab/ingest.py`, `chat_prompt.py`, `chat_session.py` | Pure upload, prompt and session transitions |
| `services/api/lab/parsers.py`, `docling_pipeline.py`, `parse_pipeline.py` | PDF converters, structured extraction and derived artifacts |
| `services/api/lab/chunking.py`, `embedding_config.py`, `hashing.py` | Chunk boundaries, tokenizer choice, embedding format and content hashes |
| `services/api/lab/index.py`, `retrieval.py` | Topic SQLite index, hybrid search and evidence assembly |
| `services/api/lab/models.py`, `context.py` | Local model gateway, streaming and prompt budget |
| `services/api/lab/storage.py` | Topic paths, original preservation, file and session records |
| `services/api/lab/document_map.py`, `document_map_store.py` | Pure native-source reconstruction and versioned outline persistence |
| `services/api/lab/section_summary.py`, `document_map_summary_store.py` | Pure full-section prompt planning, validated attempts and completed-summary persistence |
| `services/api/lab/summary_import.py` | Pure immutable generated-context snapshots and conversation-local import identity |
| `services/api/lab/web/document_maps.py`, `document_map_summaries.py`, `summary_imports.py` | Explicit outline build/read, request-bound summary streams, and existing-conversation imports |
| `services/api/lab/query_traces.py` | Pure diagnostic record construction and versioned topic-local SQLite trace persistence |
| `services/api/lab/asgi.py` | ASGI entry point |
| `scripts/dev.py`, `scripts/verify_workspace.py` | Development and verification lifecycle |
| `evals/retrieval/` | Registered real-PDF gold sets, pure anchor scoring, isolated production retrieval/trace runner |

Personal topics and their PDFs live in `../Learning/<topic>/`, outside this Git repository. Tests override those roots. Model weights and runtime state remain local and ignored by Git.

## Current limits

- Both chat routes read the configured runtime policy before retrieval or generation and include its full text in the protected system message for every selected model. Policy changes apply to the next request; unreadable/invalid policy blocks chat without a fallback. See [runtime policy loading](runtime_policy.md).

- Each topic has a default conversation and can hold additional independent saved conversations. The selected context can be trimmed for a model request; each saved history remains complete. There is no compaction. The browser remembers selected file IDs per conversation; PDFs and the learning goal belong to the topic.
- Chat requests produce local diagnostic metadata in `query_traces.sqlite`, including rejection, completion, error and cancellation outcomes. A bounded topic-scoped developer API exposes records; no new learner screen or external telemetry is involved. [Trace contract](query_traces.md). The [retrieval evaluation suite](../evals/retrieval/README.md) measures source-anchor coverage, retrieval and retained evidence while checking trace consistency. Generation is simulated; answer quality is unassessed.
- Indexed Docling files support keyword and local embedding retrieval with a trace. Cited evidence is limited to passages retained in the model prompt. Saved citation page links open the topic-scoped original PDF at the cited page when supported by the browser viewer; invalid or out-of-range targets are shown unavailable.
- Each topic can store a validated user-authored learning goal. Chat supplies it as learning context, separate from retrieved evidence. Extraction diagnostics persist parser-reported failures and suspected limitations; a clean diagnostic run and legacy parser records remain fidelity-unassessed.
- Chat is one retrieval pass followed by model streaming. No LangGraph workflow, model tool calls, approval interrupts, understanding checks or progress memory exist yet.
- Topic and path validation is implemented. It is not an execution sandbox for future code, browser or device tools.
- The model adapter can send retrieved figure images to a vision-capable local model. General multimodal R2 behavior and Mac–Jetson deployment are not implemented.

An explicit Document Map request reconstructs saved Docling source without retrieval. Section generation sends the complete section and freshly loaded runtime policy through the selected Ollama gateway, with no conversation history or learning goal. Whole-prompt preflight refuses an oversized request instead of trimming source. Import appends an immutable, labeled generated-context snapshot to an existing conversation without inference. Attempt lifecycle, compatibility and decision evidence are in the [implementation note](reports/document-map/2026_10_05_document_map_implementation.md) and [API contract](API.md). Native source accounting and valid source labels do not certify PDF fidelity or semantic support.

## Contracts to preserve

- Every retrieval and persistence operation uses an explicit topic. Originals are immutable.
- A ready indexed file with a missing index fails visibly. An unfit prompt fails before the turn is saved.
- Tokenizer fallback is labeled approximate. Exact local counts include embedding prefixes and special tokens; oversized chunks retain their source whitespace.
- Citation metadata belongs to each saved assistant answer. It must agree with the evidence sent in that answer's model request.
- Stored-format changes require a compatibility decision. Future model tools, hardware access and web research require separate validation and authorization.

Coding conventions and validation gates live in [engineering.md](engineering.md).

## Shared learner profile modules

`learner_profile.py` owns pure versioned CV/proficiency transformations; `profile_store.py` owns duplicate-safe shared originals, integrity checks and revision-locked atomic writes; `profile_parse.py` reuses normal parsing adapters for canonical complete extraction. Shared CVs live under configured `../Profile/`, independent of study topics and retrieval indexes. `prerequisites.py` owns fresh whole-input planning/schema/validation; `prerequisite_store.py` owns topic-local immutable attempts/assessments; `web/prerequisites.py` owns request lifecycle, shared generation lock and publication ordering. These remain separate from document-map native reconstruction and summaries.

`conversation_profile.py` stores per-existing-conversation opt-in/focus preferences; `learner_context.py` reloads and deterministically projects latest saved proficiency for each chat. `prerequisite_import.py` constructs immutable historical snapshots; `web/prerequisite_imports.py` explicitly adds them to an existing main conversation and activates focus, without inference. Whole canonical CV text is optional and protected in chat; it is required only for new personalized generation. Current profile context is loaded separately from historical messages and never silently inferred from CV degrees/omissions or casual chat. See [API contracts](API.md#shared-cv-my-proficiency-and-prerequisites) and the [module study walkthrough](proficiency.md). Frontend helper/page modules are composed incrementally; final browser integration and verification are recorded in dated reports.
