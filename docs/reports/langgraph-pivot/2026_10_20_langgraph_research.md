# LangGraph pivot research

Date: 20 October 2026. Separate coordinator-filed research report from the research agent (`gpt-6.1-sol`, high), prepared before design. Baseline inspected: `63d0e84`; initial planning checkpoint: `111e4a1`. Consolidated plan: [pivot_to_langgraph.md](pivot_to_langgraph.md). The researcher acknowledged the entire Code-root policy and research skill. No installs, inference, services, application writes, Git mutations or personal-data access were performed by the researcher. This report summarizes the completed handoff; it does not claim that proposed integration behavior has been exercised.

## Decision and recommendation

LangGraph is required for R1 and for Tanmay's learning objective. The earlier decision to defer it is superseded. Compare ways to integrate it, not whether it is necessary. Recommended end state: a small family of actual LangGraph workflows sharing a runtime/event boundary—chat (ordinary and extra search), section summaries, and prerequisites. Nodes represent actual stages, conditional edges own routing, and existing domain/store functions remain reusable. Wrapping the old complete orchestrator in a single node does not satisfy this pivot.

Begin with request-scoped execution and no persistent graph checkpointer. Design state/runtime boundaries now; durable resume is a separately gated R1 capability needing stable operation identity, staged output, idempotent publication, freshness checks and explicit user behavior. Adding a saver alone cannot provide those guarantees. Readability/performance benefits are hypotheses to assess, not automatic framework properties.

## Current workflow inventory and migration seams

Repository references below are relative to Code root; line references describe baseline `63d0e84` and may move during implementation.

| Workflow | Verified current responsibility | Target boundary |
| --- | --- | --- |
| Ordinary Default/named chat | Both routes share `web/chat.py`; policy/context, selected-file retrieval, prompt preflight, user save, one generation, assistant/trace finalization (`web/chat.py:97–118,205–375,628–635,709–779`). | Actual chat graph with preparation/admission and execution explicitly separated. Ordinary remains one generation. |
| Optional extra search | `evidence_turn.py:80–305`: buffered schema decision, direct answer or one more lookup/final generation; invalid-action prose fallback. | Decision/validation/search/revalidation/final-plan/generation nodes with explicit edges. Preserve call ceilings. |
| Outline build/read | Native Docling reconstruction and versioned map storage (`web/document_maps.py:23–36`, `document_map.py`, `document_map_store.py`); no chat generation. | Domain/storage service; graph nodes can consume its outputs. |
| Section summaries | Full-policy/whole-section preflight, attempt lifecycle, streaming, label/source revision checks, publication before done (`web/document_map_summaries.py:39–81,104–131,145–218`). | Dedicated graph using current planner/validator/store contracts. |
| Summary import | Explicit idempotent immutable snapshot append to existing conversation; no inference (`web/summary_imports.py:20–69`). | Domain transaction, no automatic graph/model invocation. |
| CV ingestion | Exact chosen filename, duplicate-safe shared storage, normal parser adapter, canonical full extraction (`web/profile.py:66–111`, `profile_parse.py`, `profile_store.py`). | Parsing/storage boundary, not a new conversational agent. Docling's own processing models are separate. |
| Prerequisite generation | Requires current map and eligible CV; complete policy/section/CV fit; one buffered structured generation; source/CV recheck; pending proficiency registration and assessment publication (`web/prerequisites.py:110–178,235–332`). | Dedicated graph including validation/publication/reconciliation stages. |
| Prerequisite import/focus | Idempotent snapshot append precedes focus preference update (`web/prerequisite_imports.py:43–117`). | Existing domain transaction. |
| My proficiency | Revisioned independent self-reports/manual concepts and assessment identity. | Existing domain/store functions; forms are not suspended graph interrupts. |
| Retrieval/indexing | Topic keyword/hybrid search, installed embedding model and visible degradation (`retrieval.py:24–132`). | Service called by graph nodes; upload indexing remains ingestion. |
| Other CRUD | Topic/conversation/settings/profile validation and persistence. | Ordinary API/domain boundaries. |

“Complete coverage” means all conversational/generative inference orchestration uses LangGraph and all remaining workflows are intentionally classified. It does not mean ceremonial one-node graphs for every CRUD endpoint.

## Alternatives and ownership

| Alternative | Tradeoff / decision |
| --- | --- |
| One universal operation-discriminator graph | Uniform entry point, but sparse unrelated state and accidental profile/CV coupling. Not recommended. |
| Family graphs plus common runtime/event/finalization mechanisms | Truthful per-family state and publication semantics. Recommended end state. |
| Chat-first migration ending in summaries/prerequisites and old-engine deletion | Small regression boundaries; temporary dual orchestration must have an explicit removal gate. Recommended rollout. |
| Big-bang migration | Conflates distinct lifecycle failures. Rejected. |
| One graph node wrapping old orchestration | Leaves custom orchestration authoritative. Does not meet objective. |
| Simultaneous ChatOllama/high-level agent migration | Changes message/provider/tool behavior unnecessarily. Preserve direct Ollama gateway. |
| Graph checkpoint database replaces application stores | Requires history/profile migration and competing authorities. Preserve application stores. |

[StateGraph](https://docs.langchain.com/oss/python/langgraph/graph-api) supports typed state, function nodes, conditional edges and run-scoped runtime context. Existing pure transformations fit this model. Application stores remain authoritative for published history/results/profile. Graph state carries operation identity, validated stage results, routing, counters, source references and publication outcomes. Runtime context supplies gateway/store capabilities, shared locks, captured request inputs and ephemeral prompt material. HTTP owns admission/status/NDJSON/disconnect; pure helpers own budgeting/validation/merging.

Compile reusable topology per application at the composition root. Do not create resources at module import or capture mutable requests in shared closures. Use replacement updates/pure transforms rather than adopting append reducers by habit. `MessagesState`/`add_messages` introduces LangChain message/ID semantics; it is not the existing full-history/import/citation contract. Do not duplicate that authority.

Complete question, runtime policy, learner projection, optional full CV and retained-source framing remain under deterministic prompt builders. `context.py` estimates UTF-8 bytes, reserves output room and protects required inputs; graph memory is not token budgeting. Locks, connections, open streams and tasks must not enter serializable graph state. “Private” state schemas are not a secrecy boundary for full-state/debug streaming.

## Direct gateway streaming and backpressure

Official [streaming documentation](https://docs.langchain.com/oss/python/langgraph/streaming) supports custom events from arbitrary model clients. Keep `OllamaGateway`/HTTPX; no second model, provider SDK or LangChain chat wrapper is necessary. Direct HTTP does not automatically produce LangChain `messages` events.

Published `langgraph 1.2.16` confirms `astream(..., stream_mode="custom", version="v2")`, runtime `stream_writer`, and a synchronous `Callable[[Any], None]` writer. The v3 Pregel interface is experimental. Use a version-pinned adapter and existing NDJSON schemas, never raw framework envelopes.

Allow only existing public tokens/thinking, safe extra-search status, summary attempt events, prerequisite progress, and validated domain results. Never forward raw `values`, `updates`, `debug`, task, checkpoint or callback streams. These may contain full prompts, CV, sources, private planning or raw exceptions.

Published source `pregel/main.py:3247–3252` creates `AsyncQueue()`, `_internal/_queue.py:12–15` explicitly calls it unbounded, and custom events use `put_nowait`. A synchronous token writer can let the model outrun a slow client. `max_concurrency` is not a queue bound. Credible designs:

1. An asynchronous bounded request event sink with an owned graph task and transport consumer.
2. Credit/ack gating before custom writes to bound outstanding events.

A bounded queue downstream of an unbounded producer is insufficient. Actual slow-consumer and cancellation tests must establish bounds; no experiment was run here. Published source was inspected in memory from official PyPI wheels without installing or writing packages.

## Admission, partial output and terminal ordering

Current failures for missing policy, unavailable evidence or unfit protected context precede user save/response headers. Lazily starting all graph work after returning a streaming response would change this. Design must choose explicit preparation/admission and execution phases, or prove an equivalent early boundary with generation blocked until streaming.

Provider completion, graph completion and application publication are distinct. Only required application publication permits public `done`. Chat saves the assistant before trace finalization (`web/chat.py:743–778`); summaries save attempts/completion; prerequisites register pending rows before assessment publication and reconcile ambiguous writes. Preserve each exact order and failure behavior.

A cancelled node may have emitted tokens without returning its final state update. `get_state()` therefore need not contain partial output. Preserve partial-answer/attempt accounting through a request-owned observer/finalizer. Observed events are not proof of provider/browser receipt. The current `FinalizedStreamingResponse` (`web/middleware.py:41–96`) detects silent disconnect, closes iterators and shields cleanup; adapt its ownership to include graph task/sink/provider resources rather than removing that contract.

## Cancellation, locks and pauses

Published `pregel/_executor.py:186–211` cancels flagged owned tasks and awaits them, but this is not runtime proof for our HTTPX/ASGI integration. In this version a node manually raising `CancelledError` can become `NodeCancelledError`; test actual external task cancellation, not only such fake nodes.

Keep a topic lease across an admitted request; keep the app-wide inference lock shared with embeddings; close the first decision iterator before follow-up retrieval. `max_concurrency=1` does not serialize separate graph requests. Holding the shared inference lock around the entire graph can deadlock when retrieval embeds under the same lock. Existing gateway calls should retain their own lock ownership.

Cancel and await all child tasks; shield idempotent finalization and lease release even when persistence fails. No detached generation/retrieval/checkpoint work after Stop. Moving blocking parsing/storage into a node does not make synchronous work preemptible.

[Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance) distinguishes cooperative drain, which completes a superstep, from immediate cancellation. Stop/disconnect remains terminal cancellation, not pause. Shutdown follows current cancellation semantics initially. Resume is a new explicitly authorized operation. Future [interrupt approvals](https://docs.langchain.com/oss/python/langgraph/interrupts) need durable identity and validated payloads: nodes restart from the beginning and preceding effects can repeat; broad catches must not swallow interrupts. Release leases on human pause, reacquire and revalidate on resume. Do not add approval ceremony to already opted-in selected-document read-only search.

## Checkpointing, replay and privacy

[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) distinguishes execution checkpoints from the cross-thread LangGraph Store. Initially use neither persistent checkpoints nor Store. Existing app results/history/recovery remain authoritative; no generic resume, startup replay or time travel.

Before persistent execution: version operation records; define stable publication IDs; decide durable staged output and retention; implement reconciliation; define cancellation tombstones; rebuild runtime dependencies/fresh authority; add explicit resume/approval behavior; prove crash/privacy cases. Metadata-only checkpoints cannot recover an unstaged generated answer without another generation.

The current SQLite saver owns its own checkpoint/write tables and commits. `durability="sync"` cannot atomically commit those with application JSON/profile/trace stores. Required crash behavior:

| Crash or change | Required contract |
| --- | --- |
| Model done, output not staged | Do not claim recovered output; any regenerated request is explicit and may cost another call. |
| App result saved, graph checkpoint absent | Detect existing publication, avoid duplicate append/generation. |
| Graph saved, application result absent | Publish idempotently from verified durable output or refuse unsafe continuation. |
| Profile pending rows, assessment absent | Keep exact-identity reconciliation; preserve learner-edited/manual/published rows. |
| Answer saved, trace/checkpoint completion fails | Preserve answer and truthful diagnostic/ambiguous status; no manufactured success. |
| Cancelled operation with old checkpoint | Terminal cancellation forbids execution of that checkpoint. |
| Policy/source/CV changed | Visible refusal/new authorized operation; do not mix old decisions with new context. |

Chat has no durable idempotent turn-publication key yet; trace identity alone is not that key. Summaries/prerequisites already have attempt IDs but require replay review. [Time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel) can repeat downstream effects and must remain internal until explicitly designed.

Revalidate effective policy/goal/proficiency/source identities using current snapshot rules, not raw global revision numbers. CV-off still performs no CV registry/artifact freshness reads; CV-on/new prerequisites require current eligibility/revocation checks. A checkpoint containing literal old CV text cannot override those checks. Checkpoints do not create atomic cross-store snapshots or retract in-flight prompts.

Durable identity must include workspace/app instance, workflow kind, topic, conversation where applicable, file/section/attempt as appropriate, operation ID and graph/state/protocol version. Never use bare `default` globally or accept arbitrary browser checkpoint/thread IDs as authority. One request is one operation; app conversation history remains separate. Reusing one checkpoint thread per conversation while supplying full history risks duplicate accumulated context.

`AsyncSqliteSaver` 3.1.2 captures an event loop/async lock; `from_conn_string()` is an async context manager; setup uses WAL; deletion removes table rows. Open it only through application lifespan/`AsyncExitStack` if later enabled; stop active tasks before closing. Separate test loops/app roots must not reuse connections. [SQLite saver package](https://pypi.org/project/langgraph-checkpoint-sqlite/3.1.2/).

Checkpoint 4.3.0's serializer has optional pickle fallback and permissive MessagePack module behavior by default. Choose an explicitly constrained codec, no pickle fallback, and test all framework/application types rather than enabling arbitrary deserialization. [Checkpoint package](https://pypi.org/project/langgraph-checkpoint/4.3.0/). SQLite row deletion is not secure erasure of WAL/backups/staged artifacts; encryption requires key management and does not solve stale authority.

## Preserve protocol and inference budget

LangGraph does not require native tools. Keep current strict answer-or-search JSON, selected local model, one generation for ordinary/direct, maximum two generations/one extra lookup for search, and existing disclosed invalid-action fallback. No automatic retry, new path/file/tool arguments or permissions. `ToolNode` does not supply our source authorization. Native tools require a separate protocol/capability change and should not be bundled into this migration.

Keep gateway local-only checks, `keep_alive:0`, schema temperature zero, thinking and context options (`models.py:137–247`). More graph nodes must not mean more inference calls or changed model residency.

## Version/dependency evidence and network gates

Local metadata: Python 3.13.3, Pydantic 2.13.5, HTTPX 0.28.1, FastAPI 0.141.1, AnyIO 4.15.1, Docling 2.127.0. LangGraph/Core/checkpoint/saver/LangSmith are absent.

| Published package examined | Version | Relevant metadata |
| --- | --- | --- |
| LangGraph | 1.2.16 | Python >=3.10; Core >=1.4.7,<2; checkpoint >=4.3,<5; prebuilt/SDK/Pydantic/xxhash |
| Checkpoint | 4.3.0 | Python >=3.10; Core and ormsgpack |
| SQLite saver | 3.1.2 | Python >=3.10; aiosqlite/checkpoint4.3+ and sqlite-vec |
| LangChain Core | 1.6.12 | Python >=3.10,<4; LangSmith dependency |
| LangSmith | 0.14.11 | Python >=3.10; additional HTTP/serialization dependencies |

These are candidate pins, not an installed/resolved environment. Primary metadata: [LangGraph](https://pypi.org/pypi/langgraph/1.2.16/json), [checkpoint](https://pypi.org/pypi/langgraph-checkpoint/4.3.0/json), [SQLite](https://pypi.org/pypi/langgraph-checkpoint-sqlite/3.1.2/json), [Core](https://pypi.org/pypi/langchain-core/1.6.12/json). Native wheel availability was observed for macOS ARM64/Python3.13-relevant ormsgpack, xxhash, uuid-utils and sqlite-vec; availability is not a successful resolver/install test.

Edit direct dependencies in `services/api/pyproject.toml`, exact supported lock in `services/api/requirements-macos-py313.lock`; `requirements.txt` delegates to project extras. CI is `.github/workflows/checks.yml` (macOS14/Python3.13/Node22). Review Makefile setup and verification preflight. Add SQLite only with implemented durable capability. Declare Core/LangSmith directly if application code imports them. No need for full LangChain, ChatOllama, Platform/CLI or hosted services.

LangSmith transitively present is not proof of network transmission, but tracing can be enabled by environment/configuration. Disable remote tracing at the execution boundary and test under tracing-enabled environment; empty callbacks alone are not proof. [Programmatic tracing configuration](https://docs.langchain.com/langsmith/trace-without-env-vars). Keep environment reads in `lab/config.py`. Published Core `graph_mermaid.py:277–280,405–461` defaults `draw_mermaid_png()` to API rendering at mermaid.ink: generate local Mermaid text, not network-rendered diagrams.

## Prioritized implementation gates

1. Isolated Python3.13 dependency resolution/install, exact lock, `pip check`, no import-time resources.
2. Tiny real graph/fake production-interface gateway: precise event mapping, iterator close and no sensitive leakage.
3. Actual ASGI2.3/2.4 cancellation during silence/tokens/lock wait/retrieval plus slow-consumer boundedness and no orphan tasks.
4. Admission before headers/user save, partial answers on cancellation, exact publication ordering, faults at save/trace/close boundaries.
5. All-family graph paths and call-count equivalence, including Default/named, ordinary/search, whole-section summary and CV-required prerequisites.
6. Tracing-enabled environment/network spy, CV canaries, no raw-state diagnostics and local-only diagrams.
7. Only after explicit durable slice: codec/saver lifecycle, crash/idempotency, changed authority, cancellation tombstones, stored versions and retention.

Current tests provide characterization targets: `test_evidence_chat.py`, `test_evidence_turn.py`, `test_stream_disconnect.py`, `test_document_map_summaries_api.py`, `test_web_prerequisites.py`, policy/context/profile/import suites and frontend captures. Preserve source labels/pages/images, retained/supplied counts, CV-off no-read, optional full CV, old sessions/imports, prompt-fit refusals, prior-success preservation and pending-row reconciliation.

Recommended migration order: characterization; dependency/runtime/stream/privacy spike; ordinary and extra-search chat; summaries; prerequisites; old-engine removal/full verification/docs. No shadow model runs or silent runtime fallback to the old engine. Persistent resume/approvals remains a separately defined subsequent R1 slice. No benchmarks, application tests/build or runtime spike was run for this report. Dependency compatibility, cancellation timing, memory bounds, serialization, network silence and migrated end-to-end behavior remain unverified until their gates pass.
