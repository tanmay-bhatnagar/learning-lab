# LangGraph pivot validation research

Date: 20 October 2026. Separate research report, prepared by the coordinator session following the research skill (Claude Opus, at Tanmay's instruction that research and design run in the main session rather than as sub-agents). Purpose: validate the [consolidated plan](pivot_to_langgraph.md) against the live repository and the actual published package, before design gap-filling and implementation. Application baseline: `dd9774d` on `dev` (application code identical to `63d0e84`). The earlier [research](2026_10_20_langgraph_research.md) and [design](2026_10_20_langgraph_design.md) reports remain unchanged; this report supplements them with executed evidence. Its companion is the [validation design](2026_10_20_langgraph_validation_design.md).

I acknowledged the Code-root development policy and research skill. No application code, project environment or personal topic was changed. Spikes ran in an isolated throwaway virtual environment (`/tmp/lgr/spike`: LangGraph 1.2.16 plus the project's locked FastAPI/Starlette/AnyIO/HTTPX/Pydantic versions). Spike scripts and raw outputs are preserved, ignored, under `.local/verification/reports/langgraph-pivot/research_spikes/`.

## Question

Does the plan's selected mechanism hold when exercised, rather than read? That mechanism is family graphs, awaited admission, an owned `graph.ainvoke()` task feeding a bounded application sink, one publisher per family, the existing `FinalizedStreamingResponse`, and suppressed tracing. Which assumptions are wrong or missing?

## Baseline

- `make test` backend portion: **683 passed, 21 subtests**, 35 s (`.local/.../baseline_pytest.txt`). This matches the plan's historical count.
- OpenAPI captured from `create_app` with isolated roots: 37 paths (`.local/.../baseline_openapi_dd9774d.json`). This is the comparison point for gate 16.
- PyPI: LangGraph **1.2.16 is still the latest release** on 20 October. The research candidate pins remain current.

## Verified findings

| # | Experiment | Observed result | Consequence for the plan |
| --- | --- | --- | --- |
| R1 | `pip install --dry-run` of the full existing lock plus `langgraph==1.2.16` | Resolves with **zero changed pins** and **21 new packages**: langgraph, langgraph-checkpoint 4.3.0, langgraph-prebuilt 1.1.1, langgraph-sdk 0.4.8, langchain-core 1.6.12, **langchain-protocol 0.0.19**, langsmith 0.14.11, jsonpatch, jsonpointer, orjson, ormsgpack, xxhash, uuid-utils, tenacity, zstandard, requests-toolbelt, sniffio, **distro, httpx2/httpcore2 2.15.1, truststore** | Plan confirmed: no unrelated upgrades. Missing from prior research: LangSmith brings a *second* HTTP client stack (`httpx2`/`httpcore2`/`truststore`), and Core requires `langchain-protocol`. All must be pinned exactly and reviewed in the lock delta. `pip check` passed in the spike environment. |
| R2 | Read `langgraph/_internal/_config.py` | `DEFAULT_RECURSION_LIMIT = int(getenv("LANGGRAPH_DEFAULT_RECURSION_LIMIT", "10007"))`; a 5-step limit raises `GraphRecursionError` | Plan says the recursion limit is a secondary guard. The default is effectively unbounded and environment-controlled, so the guard exists **only** if every run passes an explicit, topology-derived `recursion_limit`. |
| R3 | Hostile inherited tracing environment (`LANGSMITH_TRACING=true`, fake key, unroutable endpoint), set before import, socket `connect` spy | Without suppression: `LangChainTracer` attached; **3 outbound connection attempts**, including `POST /runs/multipart` with a 3,897-byte payload | Confirms the privacy risk is real, not theoretical. Graph state would be uploaded. |
| R3a | Same, `config={"callbacks": []}` | Still **2 outbound attempts** | Confirms plan: empty callbacks are not suppression. |
| R3b | Same, `with langsmith.tracing_context(enabled=False): await graph.ainvoke(...)` | No tracer handler; **0 attempts** | Verified mechanism. Because context variables are copied at task creation, it must wrap the coroutine *inside* the owned task (and the awaited admission call). The application then imports `langsmith` directly, so it must be a declared dependency. |
| R4 | Cancel `ainvoke` task while a node is inside `anyio.CancelScope(shield=True)` | Shielded work **was interrupted**. LangGraph cancels with native `task.cancel()`, which AnyIO's shield does not intercept | **Plan gap.** Current publication code relies on AnyIO shields, which work only because Starlette's AnyIO task group owns that cancellation. Inside graph nodes, short publication must use `asyncio.shield` of a single publication task, then await that same task before re-raising. That pattern completed the publication under cancellation. |
| R5 | Sync node and sync conditional-edge function under `ainvoke` | Both ran on thread `asyncio_0` (executor) | **Plan gap.** A sync node doing store I/O would leave the event loop, could not be cancelled, and would race shared locks. Every node and router must be `async def`. |
| R6 | Node raises `LookupError`; inspect input dict; identity of `runtime.context` | Original exception type propagates from `ainvoke`; caller input unmutated; context object identity preserved across nodes; **no automatic retry** (one call; `retry_policy=None` default) | Plan's domain-error mapping at HTTP remains valid without wrapping. Runtime context can safely carry request-owned capabilities by reference. |
| R7 | 8-slot `asyncio.Queue` sink, no consumer, 100-token provider | Producer blocked after 9 accepted tokens (8 queued plus 1 accepted, awaiting `put`) | Confirms bounded backpressure and the plan's "observer records accepted text before blocked enqueue." |
| R7a | External cancel of that task | `CancelledError` raised from `ainvoke`; provider `finally` ran (`aclose`); no orphan tasks | Confirms owned-task cancellation and iterator closure. |
| R8 | **Production** `lab.web.middleware.FinalizedStreamingResponse` + graph task + bounded sink; disconnect mid-stream; ASGI spec 2.3 and 2.4 × with/without `BaseHTTPMiddleware` × silent provider / slow reader / fast reader (12 cases) | Every case: `on_close` ran, graph task finished, provider closed, slow reader capped at 10–11 accepted tokens. Two timeouts occurred only where the harness's `send` never returns behind `BaseHTTPMiddleware`; the baseline response would equally hang | The middleware likely needs **no change**. First run leaked a pending `Queue.get` task on disconnect; cancelling the consumer's pending get in `finally` produced **0 leaked tasks** in all 12 cases. Required consumer rule. |
| R9 | One compiled graph run under two `asyncio.run` loops and another thread | Correct results each time | Compile once at app composition; tests that use `TestClient` or repeated `asyncio.run` remain safe. |
| R10 | Thread count before/after importing LangGraph/Core | 1 → 1 | No import-time threads. Note: LangGraph itself reads `LANGGRAPH_DEFAULT_RECURSION_LIMIT` at import. That is third-party, not `lab/`, so the `config.py` rule is unaffected, and explicit `recursion_limit` (R2) neutralizes it. |
| R11 | `get_graph().draw_mermaid()` | Text produced locally; no network | Plan confirmed. Never call `draw_mermaid_png()` with default API rendering. |
| R12 | Frontend `state/chatStream.ts`, `state/documentMap.ts`; prerequisites use `progress` only | Token/thinking events are concatenated | Splitting a large validated direct answer into ≤8 KiB fragments is wire-compatible. |

## Repository claims rechecked

The plan's code citations are accurate for `dd9774d`. Chat preflight saves the user at `web/chat.py:362–364` after the protected-fit plan. Early trace insertion at `:137` precedes lease acquisition at `:184`, so a busy-topic rejection produces a trace but no user. Generation starts only inside the response iterator. Assistant save precedes trace finalization at `:747–766`, and trace failure replaces `done` with the "answer was saved" error. Summary and prerequisite routes write the generating attempt before `lease.hand_off()` and emit `started` first. Prerequisite publication registers pending rows (`register_model_requirements`) before writing the assessment, then reconciles by exact attempt/assessment identity on failure. `evidence_turn.py` has the stated ceilings, and `_consume_decision` closes the decision stream before lookup. All four suites named in plan §9 exist.

## Alternatives the evidence supports or rules out

- **Bounded application sink plus owned `ainvoke` task**: supported by R7, R7a and R8. **Credit-gated custom writer**: not needed. Kept as the fallback only if later gates expose a failure.
- **AnyIO shield in nodes**: ruled out by R4. **`asyncio.shield` with a single awaited publication task**: verified.
- **`callbacks=[]` for privacy**: ruled out by R3a. **`langsmith.tracing_context(enabled=False)` inside the task**: verified by R3b. Alternative of mutating `os.environ` at startup: rejected. It is global, violates the `config.py` rule, and LangSmith caches environment reads.
- **Middleware rewrite**: not justified by R8. Keep `FinalizedStreamingResponse`; let the run handle own its task and getter.

## Remaining uncertainty and owners

Unverified until the named gates: the exact lock install inside the project environment (gate 2, coder; tester verifies). Full-app behavior under real `TestClient` and the existing disconnect suites (gates 5–7). Real Ollama/HTTPX close timing (gate 16 usage). Overhead of graph scheduling per token (measure before any performance claim). Terminal payload sizes (gate 3 analysis). Conditions that would change the selected branch: a failing disconnect or backpressure test against the production app; a resolver conflict in the real environment; LangGraph cancellation not propagating through a lookup child task.
