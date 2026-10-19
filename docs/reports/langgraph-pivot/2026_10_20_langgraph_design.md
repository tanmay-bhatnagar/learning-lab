# LangGraph pivot design

Date: 20 October 2026. Separate coordinator-filed design report from the configured design agent (`gpt-6.1-sol`, medium, read-only), following the [completed research](2026_10_20_langgraph_research.md) at `ad0ae27`. Application baseline inspected: `63d0e84`. Consolidated implementation plan: [pivot_to_langgraph.md](pivot_to_langgraph.md).

The designer acknowledged the entire Code-root policy, assignment and design skill, read the research and relevant implementations, and changed no files, Git state, dependencies, services or models. This is a proposed design, not runtime proof. The coordinator has organized the handoff here and clarified that admission writes occur exactly once inside admission, not again in the HTTP adapter.

## Selected architecture and alternatives

Three workflow families—chat, section summary and personalized prerequisites—each have an awaited admission graph and request-bound execution graph. Actual nodes and edges own stages/routing; existing domain functions retain source validation, budgeting, transformations and store contracts. Initial execution is request scoped, with no persistent checkpointer or LangGraph Store.

| Choice | Evidence / consequence | Selected branch |
| --- | --- | --- |
| Lazy single graph after response construction | Would move preflight refusals after headers/user save. | Reject. |
| Start one graph before headers and pause at handshake | Can preserve semantics but adds a live pre-response task/cancellation boundary. | Credible fallback if two-phase design fails tests. |
| Await admission, then execute admitted operation | Explicit independently testable HTTP boundary; no interrupt/checkpoint needed. | Select. |
| Universal graph | Sparse unrelated state and accidental CV/profile coupling. | Reject. |
| Family graphs with common runtime | Truthful family schemas and publication behavior, shared lifecycle. | Select. |
| Wrap complete old engine in one node | Does not transfer workflow decisions to LangGraph. | Reject. |
| Custom writer token streaming | Research found an unbounded queue; credit gating adds another protocol. | Use bounded asynchronous application sink first. |

All conversational/generative orchestration moves to graphs: ordinary/extra-search Default and named chat, summaries and prerequisites. Outline reconstruction, parser/indexing services, explicit imports, My proficiency and CRUD remain ordinary domain/API functions. Embeddings retain their gateway/shared lock, including during ingestion. Graphs call these capabilities; a graph is not required around every operation.

## Admission contract

HTTP validates identity and acquires the existing topic lease, then awaits admission. Admission captures current context, performs retrieval/planning/fit checks and finally writes the user turn or generating attempt. The final admission node is the single admission write; HTTP must not repeat it. Existing early diagnostic trace creation remains early, so rejected chat may have a trace but no saved user.

No chat generation starts during admission. Existing retrieval embedding and capability reads may occur exactly as today. On failure, cancellation after an admission side effect, or response-construction failure, the outer owner finalizes immediately and releases the lease; it cannot rely on response consumption that may never happen.

Chat admission: capture validated session/selection/fresh context → initial retrieval → retained evidence/images → ordinary or structured prompt → protected budget → save user.

Summary admission: recover inactive attempts → current map/section → fresh full policy → whole-section plan/fit → generating attempt.

Prerequisite admission: recover/reconcile inactive attempts → map/section → eligible CV/canonical text/integrity → fresh policy/goal → complete-input schema plan/fit → generating attempt.

## Chat execution and hard budgets

Ordinary branch: stream one answer → publish assistant and trace.

Opt-in branch: revalidate captured context/initial sources → one privately buffered decision → validate action:

- Valid answer: expose the validated complete answer → publish.
- Completed invalid action: build disclosed fallback prose plan → revalidate final supplied context → stream one prose answer → publish.
- Valid search: revalidate → one selected-document lookup → scope validation/merge → final prompt → revalidate → stream one final answer → publish.
- Failed, incomplete, oversized or unterminated decision: fail visibly, with no repair generation.

Ordinary/direct paths use one generation; searched path at most two generations/one additional lookup; invalid action retains the existing second-generation fallback and zero extra lookup. Initial retrieval is separate. No automatic node retries. Finite edges and counters enforce the budget; recursion limit is a secondary safety guard. No native tool protocol, `ToolNode`, arbitrary model paths or new approvals are introduced. Already opted-in read-only selected-document search needs no extra approval ceremony.

Keep available/prepared, retained, actually supplied-at-dispatch and model-declared sources distinct. Gateway factory failure retains invocation-attempt accounting but does not mark prepared sources supplied. Factory success still does not prove provider receipt. Observer updates must preserve these milestones even if a node is cancelled before returning. Close the decision iterator before lookup embeddings acquire the same model lock.

## Summary and prerequisite execution

Summary: provider stream → complete/text/marker validation → current map revision check → publish completed summary → permit done. Failure/Stop preserves prior success; partial output belongs to the current attempt. Labels establish membership, not semantic entailment.

Prerequisites: one privately buffered schema generation → require provider completion/close → current map/CV eligibility/text check → structured requirements/reference validation → pending row registration → assessment publication → exact-identity reconciliation → permit done. No partial JSON/cards or private thinking is exposed. Each requirement retains its deterministic independent familiarity question; manual proficiency survives.

If a publication exception occurs after the assessment actually saved, reread exact attempt/assessment and return that result. If absent, clean only that assessment's eligible unpublished rows. Never delete manual, answered, differently identified or published rows. If saved state cannot be read, preserve rows and disclose uncertainty rather than assuming absence. Recovery is the current application mechanism, not graph resume.

## State and runtime

Use replacement updates, not `MessagesState`/append reducers that duplicate application history. Routing DTOs carry identity/version, stage/route, source projections/digest, plan slots/retained IDs, invocation attempts/dispatch identity, provider outcome, validated result reference and publication status. Round-trip the deliberately serializable DTOs, while explicitly not claiming every current domain object is already durable-compatible.

Run context carries explicit app gateway/store/retrieval capabilities, shared inference lock, request topic lease, captured settings, confidential policy/question/history/CV/source/image input, prompt/result artifact slots, bounded sink, observer, publisher and explicit clock/ID dependencies. No locks, clients, tasks or full confidential prompts in future checkpoint state.

A request-local artifact holder references immutable confidential inputs and owns plan/result slots; it is not a new durable learner store. Nodes do not mutate shared closures or caller-owned domain records. A later durable adapter must replace ephemeral references with verified staged artifacts or refuse resume; references alone do not recover lost output.

Compile topology per app in the composition root, with fresh context per run. App lifespan tracks/cancels active runs. No import-time graph resources, clients, tasks or connections.

## Bounded streaming and observer

Execute `graph.ainvoke()` in an owned task. Nodes await a bounded async sink; the HTTP consumer reads only existing allowlisted application events. Proposed initial outstanding-event capacity: eight, subject to spike results. Split text fragments at a bounded UTF-8 size, initially 8 KiB without splitting characters; await capacity before reading more provider events. Coalesce safe duplicate progress only when ordering remains valid.

Fragmentation may change event granularity, not concatenated content or event schema; prove this with captured-wire/frontend parsing tests. Terminal domain objects retain their schema and need separate size analysis. The queue bounds outstanding transport buffering, not total memory: complete answers/JSON, source plans, history and one parsed provider event can still be large. Do not pre-materialize all fragments or claim a globally fixed memory footprint.

The request observer records accepted content/thinking before blocking on send, hidden structured buffer/bytes separately, factory/dispatch/supplied-plan milestones, call counts, provider completion/close/errors, publication and timings. It exists because cancelled nodes may never return graph state updates. It is neither durable learner memory nor proof of browser receipt.

Never expose raw graph values/updates/debug/checkpoint/callback envelopes. Planner JSON, CV context and raw exceptions remain private under the existing policy.

## One publisher and teardown

Each family publisher is invoked by normal graph publication and cancellation/error finalization. HTTP does not have a competing save path. Per-request publication latch/critical section prevents duplicate live-request finalization, not crash-safe exactly-once behavior.

Chat: construct assistant from observer/actual supplied plan → save assistant/context → finalize trace → permit done. Save-success/trace-failure preserves answer, exposes the existing diagnostic error and never appends a second incomplete assistant. Stop/error retains the current incomplete-answer contract, including empty incomplete results where appropriate.

Summary publisher requires validated provider completion, current map and durable attempt/result write. Failure updates only the new attempt. Prerequisite publisher owns registration/publication/reconciliation; finalizer delegates rather than deleting rows independently.

Shield only short publication/outcome bookkeeping, never generation, queue waits or retrieval. Cancellation after actual save must not create an incomplete overwrite. Inject cancellation around each save boundary.

Teardown: close transport → cancel owned graph/lookup → await termination and close providers → shield family finalization → unregister active run/attempt → release lease in outer finally. Use a completion signal/task outcome rather than enqueueing a sentinel into a full abandoned queue. Live consumers can drain pending events; disconnected cleanup cannot depend on them. Preserve original failure stage and safe secondary errors even if close/trace/publication/release fails. Keep characterized family-specific error sequence semantics; do not silently normalize them during migration.

Preserve `FinalizedStreamingResponse` and actual ASGI2.3/2.4 silent-disconnect behavior. `max_concurrency=1` does not replace app-wide inference serialization. Holding the inference lock around a whole graph can deadlock lookup embeddings. Stop is cancellation, not drain/pause.

## Context and freshness

Reuse current planners and snapshot projections: complete runtime policy/question protected; CV-off no registry/artifact reads; CV-on full canonical extracted text in each applicable prompt; prerequisites full section and eligible CV, not retrieval snippets. Manual proficiency changes affect the next relevant request. Preserve retained/source/page/image identity and count semantics. Unfit protected input fails visibly, never hidden summarization/repair.

Do not add a generic global-profile revision guard. Unrelated changes may not affect effective context; CV-off must not begin reading CV. Do not silently strengthen every family's mid-generation policy: summary currently rechecks map before publication, not continuous policy freshness. Preserve the actual contract and require fresh authority in later resume design. No claim of atomic snapshots or retraction of already dispatched text.

## Dependencies/privacy

Use research candidate pins only after isolated resolution; edit `services/api/pyproject.toml` and the supported macOS/Python3.13 lock. Preserve unrelated locked versions unless a resolver conflict is demonstrated. Declare directly imported Core/LangSmith APIs as dependencies. No saver before durable capability; no full LangChain, ChatOllama, hosted service/CLI or new provider SDK.

Disable remote tracing programmatically around both graph phases and task creation/child work. Empty callbacks alone do not prove suppression. Keep environment reads in `lab/config.py`. Test hostile inherited tracing settings with allowed local Ollama and rejected unexpected network; check CV canaries in diagnostics/logs. Generate Mermaid text locally, not default network images.

## Module disposition

Proposed paths are design names, not existing files. Combine only when cohesive; no forwarding-only modules.

| Existing module/group | Disposition and target |
| --- | --- |
| `web/chat.py` | Retain routes/read APIs, extract orchestration into `workflows/chat.py`; HTTP admission/response adapter only. |
| `evidence_turn.py` | Remove when all branches migrate; preserve pure helpers in existing domain modules or cohesive `evidence_result.py`. No old workflow wrapper. |
| `chat_prompt.py`, `chat_session.py`, `context.py` | Retain pure contracts. |
| `evidence_prompt.py`, `evidence_request.py`, `evidence_snapshot.py` | Retain validation, prompt, scope and freshness. |
| `web/document_map_summaries.py` | Retain route, delegate to `workflows/summary.py`. |
| `section_summary.py`, `document_map_summary_store.py` | Retain planning/validation/storage. |
| `web/prerequisites.py` | Retain read/recovery routes, delegate orchestration to `workflows/prerequisites.py`. |
| `prerequisites.py`, `prerequisite_store.py` | Retain schema/domain/authoritative records. |
| Family publication closures | Extract into `workflows/chat_publication.py`, `summary_publication.py`, `prerequisite_publication.py`. |
| `web/middleware.py` | Retain/minimally adapt finalized stream/disconnect semantics. |
| `web/deps.py`, `web/app.py` | Compose app-owned topology/runtime and lifecycle. |
| `models.py`, `contracts.py`, retrieval/index/parsers/profile/imports | Retain domain services and gateway; no simultaneous provider migration. |

Shared new responsibilities: `workflows/types.py` (DTO/runtime protocols), `events.py` (allowlist/bounded sink), `runtime.py` (observer/artifacts/tasks). Add `web/workflow_response.py` only if a cohesive HTTP adapter is needed; do not create a second lifecycle engine.

## Sixteen passing gates

Every gate may contain red characterization/architecture test, WIP, repair and passing commits. Commit tracked loop changes immediately; passing required checks precede the next dependent gate. Coordinator owns Git/docs/integration; one coder per assigned path; review/usage read-only except explicitly assigned reproduction.

| Gate | Scope | Passing evidence |
| --- | --- | --- |
| 1 | Baseline contract fixtures/characterization | Pass on baseline; record OpenAPI and synthetic event/history/trace outputs. |
| 2 | Dependency/lock resolution | Isolated install, pip check, imports, unrelated-lock review. |
| 3 | Channel/observer/types | Slow-consumer backpressure, Unicode, accepted partial output, private event rejection. |
| 4 | Real graph task/app lifecycle | Cancellation/await, separate runs, no import effects. |
| 5 | ASGI/privacy seam | 2.3/2.4 silent/token/full-queue cancellation; failure cleanup; tracing/network canaries. |
| 6 | Chat admission | Both routes, early refusal/no user, CV-off/no-read and CV-on/full, legacy imports. |
| 7 | Ordinary generation/chat publisher | One call; partial saves; answer-before-trace; trace failure/no duplicates. |
| 8 | Decision/direct nodes | Buffered private output, direct one call, factory provenance; invalid/provider-failure distinction. |
| 9 | Invalid-action fallback | Disclosed prose fallback, no lookup, truthful final sources/counts. |
| 10 | Extra-search nodes | Scope/images/freshness, one lookup, close-before-embedding, cancellation. |
| 11 | Summary admission | Whole input/fit/current map, attempt after preflight. |
| 12 | Summary execution/publication | Labels, EOF/error, prior success, Stop and save failure. |
| 13 | Prerequisite admission/buffering | Missing CV/no calls, complete input, bounded JSON, no partial cards. |
| 14 | Prerequisite validation/publication | Freshness, pending-row/ambiguous-write reconciliation, protected manual/answered rows. |
| 15 | Old engine deletion | All production inference orchestration graph-owned, no fallback/shadow/temporary switch. |
| 16 | Full verification/docs/R1 reconciliation | Full gates, independent review, isolated actual parser/model/browser proof and study notes. |

Do not shadow-run or invoke the old engine after graph failure. Prefer direct route cutover per passing family; temporary internal switches, if needed, are removed at gate15. Rollback is an explicit deployment/commit decision to a verified checkpoint, with record compatibility checked.

Characterization tests pass before code movement; new graph architecture tests may start red but are labeled honestly. Mechanical extraction/moves get separate commits with AST/output proof. Graph routing, cancellation and publication changes are behavior-sensitive, not mechanical simply because many lines moved. Migrate old `test_evidence_turn.py` assertions to graph tests rather than retain a production wrapper for tests.

## Verification and extensions

Use existing evidence, snapshot, disconnect, protected-context, learner-context, summary, prerequisite-store/import/API suites and new real-graph tests. Full engineering, Ruff/format, web lint/format, `make test`, `make build` and isolated verification are required; stricter setup-tooling Ruff applies when changed. Existing suite paths were verified by coordinator. Actual synthetic browser/model acceptance includes ordinary/direct/search/fallback, CV modes/proficiency, sources/images, whole-section summary/Stop/import, prerequisite generation/history/import, all-stage cancellation, legacy reload and cross-topic/app isolation. Some injected failures remain automated rather than real model runs; label them.

Durable resume remains a separate explicit R1 capability: stable idempotent operation keys, cancellation tombstones, staged outputs, constrained codecs/no pickle, lifespan-owned saver, fresh dependencies/authority on resume, graph/app reconciliation, explicit UI, crash/version/retention/WAL tests. Do not replay on startup automatically. A checkpoint without staged answer text cannot recover that text; sync durability is not a cross-store transaction. Pause releases leases and resume revalidates; Stop stays terminal.

Future understanding checks become a new family graph using existing gateway/source/publication boundaries. Progress memory is domain data plus context projection. Retrieval tools extend validated action nodes, approvals add later authorization/interrupt integration, restart uses operation/staging adapters, compaction is a separate provenance-preserving context transformation. These are extension points, not already implemented features or a promise of zero future refactoring.

Reconcile the stale Code R1 snapshot and both system-map source/rendered HTML after actual completion; preserve historical validation. Mark prerequisites/proficiency/CV/extra-search implemented, LangGraph complete only after gate16, and leave understanding/memory/approvals/compaction distinct.

## Learning and unresolved gates

Learned: admission, partial-output accounting and publication are stronger contracts than “graph finished.” Selected family graphs plus bounded sink/observer/publisher make the stages teachable without replacing domain modules. Tradeoff: explicit lifecycle code beyond a tutorial and no initial durable execution; benefit: no hidden buffering assumption or duplicate conversation authority.

Verified: current repository ordering, call ceilings, module seams, CV-off behavior and configured role. Unverified: dependency resolution, actual graph cancellation/child cleanup, tracing suppression, queue/event memory, exact transport equivalence and migrated E2E. Coder implements each gate; reviewer/tester verifies independently.

If sink/cleanup fails, revise runtime before product migration; credit-gated custom streaming remains an alternative. If pins conflict, report exact conflict instead of broad upgrades. If two-phase admission cannot preserve semantics, reconsider the pre-response handshake with characterization. If durable resume enters implementation scope, complete its operation/staging/privacy gates before saver activation.

No new broad external search was needed by design because completed research supplied current APIs/source evidence; repository tracing resolved application choices. No runtime spike or test was run by the designer.
