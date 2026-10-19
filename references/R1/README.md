# R1 current state

Completion status reconciled with the ordered roadmap on 20 October 2026; historical validation is labeled below. The [interactive system map](system-map.html) has two layers; select a block to see its components. [Editable diagram source](system-map.fragment.html). The full ordered plan remains in [R1.md](../../../R1.md).

## Built

- Topic-scoped browser workspace: PDF upload and viewer, attached files, settings, local model and reasoning controls, saved chat, context meter.
- Docling ingestion: structured text, Markdown, provenance, page and figure images, bounded chunks. MarkItDown and AnyDoc remain Markdown alternatives.
- Topic SQLite keyword and embedding index, ranked retrieval, trace view, and per-answer citations that survive reload. Chat uses one retrieval pass before streaming a local Ollama response.
- Request-local context trimming preserves durable history. The five reviewed ingestion and retrieval bugs were fixed; missing indexed evidence and unfit prompts now fail visibly.
- Project engineering rules, six role configurations and skills, CI, isolated tests and HTTP verification. Development policy is self-contained in Code-root AGENTS.md.
- Citation page links, persistent topic learning goals, and extraction diagnostics.
- Multiple saved conversations per topic, developer query traces, and a three-public-paper retrieval/trace baseline with simulated generation.
- Shared runtime learning policy loaded before every chat and section-summary request, independent of selected model; visible policy-read and context-fit failures.
- On-demand single-PDF outlines, complete-section local summaries, source inspection, and immutable imports into the selected existing main conversation. [Implementation and decision history](../../docs/reports/document-map/2026_10_05_document_map_implementation.md).
- Personalized section prerequisites from a selected CV, and optional per-message extra document search (one app-executed lookup at most) in chat. See [proficiency](../../docs/proficiency.md) and [extra document search](../../docs/evidence_search.md).
- Request-scoped LangGraph admission and execution graphs for chat, section summaries and prerequisites, with unchanged HTTP contracts. See the [workflow study path](../../docs/workflows.md).

## R1 still to build

Order 6 (inferred prerequisites) is complete. The LangGraph part of orders 7–8 is complete; graphs are request-scoped with no checkpointer, tools or interrupts.

| Order | Work |
| --- | --- |
| 7–8 | Retrieval tools, tool-call validation and scoped approvals on the LangGraph workflows. |
| 9–10 | Understanding checks, topic progress memory and restart recovery. |
| 11–12 | Full R1 acceptance demonstration, then context compaction. |

The ingestion and retrieval refactor and the subsequent functional-design refactor are implemented. The 1 October [architecture review](../../docs/reports/architecture/architecture-review.md) records their findings and design; current ownership and conventions are in [architecture](../../docs/architecture.md) and [engineering](../../docs/engineering.md). Completed handoff and task-brief files were removed on 3 October at Tanmay's request. Coding experiments, web research, full multimodal support and Jetson hosting belong to later releases. The 107-PDF parser comparison remains deferred until Tanmay explicitly requests it.

## Historical refactor validation — 30 September 2026

- 128 Python tests and 17 frontend tests passed after the refactor, along with the production web build. Earlier Ruff, engineering configuration, and GitHub CI checks passed on `b2a6b71`.
- Isolated real HTTP upload/conversion/persistence passed with MarkItDown and a synthetic PDF; original bytes were preserved.
- Retrieval and citation integration tests exercised the actual model adapter with mocked HTTP. Independent review caught a whitespace regression in oversized code chunks; it was fixed and re-reviewed without further findings.
- The current Docling path has targeted unit and synthetic integration tests. This snapshot does not certify real-model answer quality, the full browser chat journey after the latest changes, difficult PDF extraction quality, or the full parser corpus.

Sources: [architecture](../../docs/architecture.md), [API contract](../../docs/API.md), [validation history](../../docs/reports/foundation/validation.md), and the committed tests. Local bug-fix reports are organized under ignored `.local/verification/reports/`; related run artifacts remain under `.local/verification/`; it contains no personal topic data.

3 October follow-up: the multi-conversation increment is implemented and validated locally on `dev`, with changes uncommitted at that time. Those changes were committed locally on `dev` on 5 October in scoped checkpoints. See [resume validation](../../docs/reports/conversations/2026_10_03_resume_validation.md) for the skills inventory, two repaired frontend races, full passing gates, real Docling/local-model citation run, persistence choices, and coverage limits.

Per-query trace logging is also implemented: topic-local metadata storage, developer inspection API, and lifecycle/failure diagnostics for Default and named conversations. See [query traces](../../docs/query_traces.md) for the contract and verification. The separate [retrieval evaluation baseline](../../evals/retrieval/README.md) is implemented using three registered public PDFs, with simulated generation and descriptive retrieval scores. See [eval validation](../../docs/reports/retrieval-evaluation/retrieval_eval_validation.md) for results and limits. The approved on-demand Document Map increment is implemented; inferred prerequisites remain outside this increment. Tanmay's on-demand requirement supersedes the earlier roadmap suggestion of automatic background summaries. Final lifecycle validation is recorded in the implementation note.

## Current validation and policy separation — 4 October 2026

The latest application baseline passed 262 backend tests plus 21 subtests, 90 web tests, and engineering/lint/build checks on 3 October; see [retrieval eval validation](../../docs/reports/retrieval-evaluation/retrieval_eval_validation.md). The 4 October instruction cleanup does not rerun or relabel that application baseline. It preserves all six exploration principles, updates all six roles and skills, and separates the parent learning policy from coding instructions. The subsequent runtime-loading increment reads the parent policy before every chat request and supplies the complete text to prompt assembly. No additional learning skills or model tools were enabled. See [runtime policy loading](../../docs/runtime_policy.md) for current verification and limits.

Runtime-policy follow-up validation: 282 backend tests plus 21 subtests and 90 web tests passed on 4 October, together with engineering/lint/format/build gates and isolated browser requests on two installed models. See [runtime policy loading](../../docs/runtime_policy.md) for per-request loading, topic binding, failure/recovery checks, evaluation snapshot provenance, and coverage limits.

## Local checkpoint commits — 5 October 2026

The previously uncommitted conversation, query-trace, retrieval-evaluation, runtime-policy, and engineering-policy changes are now recorded as scoped local commits on `dev`. No remote push, merge, or release was performed. Mandatory checkpoint commits now apply to all development roles, including failing intermediate code/test-loop states; see [checkpoint policy](../../AGENTS.md#mandatory-checkpoint-commits).

Fresh complete-working-tree checks passed: 282 backend tests plus 21 subtests, 90 web tests, production web build, engineering checker, Ruff, Python formatting, ESLint, Prettier, and six development-skill validations. Individual intermediate commits were not tested independently. Browser, real-model/parser evaluation, and isolated HTTP verification were not rerun during this commit session. Existing dependency deprecation and bundle-size warnings remain.

## Document Map validation — 5 October 2026

The approved five-slice on-demand increment is complete locally on `dev`:341 backend tests plus21 subtests,109 web tests, production build and static gates pass. Independent review clears19 focused frontend cases; actual isolated Docling/Qwen browser use verifies explicit generation, Stop with previous-result preservation, live tab survival, saved reuse, named/default idempotent imports and subsequent ordinary main chat. Generated source labels do not certify semantic claim support; grouped-marker output was visibly refused while the older successful result remained available. Inferred prerequisites remain pending. See the [consolidated implementation note and study path](../../docs/reports/document-map/2026_10_05_document_map_implementation.md) for attribution, checkpoints, actual failures, compatibility and coverage limits.
