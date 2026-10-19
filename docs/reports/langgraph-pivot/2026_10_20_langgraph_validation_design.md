# LangGraph pivot validation design

Date: 20 October 2026. Separate design report, prepared by the coordinator session following the design skill (Claude Opus; Tanmay directed that research and design run in the main session). Input: the [consolidated plan](pivot_to_langgraph.md), the earlier [design](2026_10_20_langgraph_design.md), and the executed [validation research](2026_10_20_langgraph_validation_research.md). Baseline: `dd9774d`. This report validates the plan section by section and fills its gaps with concrete contracts. It does not supersede the plan's selected architecture; it amends specific mechanisms (marked **Amended**) where executed evidence showed the plan was silent or would fail.

I acknowledged the Code-root development policy and design skill. No application code was changed.

## Section-by-section validation

| Plan section | Verdict | Evidence / change |
| --- | --- | --- |
| §1 Why / §2 scope and completion boundary | Holds | Workflow inventory rechecked against code (research report, "Repository claims rechecked"). Classification of non-generative workflows stays. |
| §3 Family graphs, awaited admission then execution | Holds | R6/R8: admission exceptions propagate with original type, so existing HTTP mapping works unchanged. Execution in an owned task survives all 12 ASGI disconnect cases. |
| §3 Existing HTTP gateway, no ChatOllama | Holds | Nodes call `ModelGateway.stream_chat` directly; R1 shows no LangChain model package is needed. |
| §3 Bounded async sink vs custom writer | Holds, now verified | R7, R7a, R8. Credit gating stays the documented fallback. |
| §4 State kinds, no `MessagesState` | Holds | Replacement channels are LangGraph's default for `TypedDict` keys. |
| §4 Runtime context and artifacts | Holds; contract specified below | R6: `runtime.context` identity is preserved, so request-owned holders work by reference. |
| §5 Bounded stream | Holds; consumer rule **amended** | R8: the consumer must cancel its pending get. Terminal events bypass the queue (below). |
| §5 One publisher, shielded bookkeeping | **Amended** | R4: AnyIO shield fails inside nodes. Use the `PublishOnce` latch below. |
| §5 Teardown order | Holds | R7a/R8: cancel, then await the task, then finalize, then release the lease in outer `finally`. |
| §6 Behavior matrix | Holds | Encoded as gate acceptance. Gate 1 audits coverage. |
| §7 Dependencies and privacy | **Amended** | R1: 21 packages, including a second HTTP stack. R3b: `tracing_context` is the verified mechanism, so `langsmith` becomes a declared direct dependency. |
| §7 Recursion guard | **Amended** | R2: explicit `recursion_limit` is required on every invocation. |
| (not covered) Node execution model | **Added** | R5: all nodes and routers are `async def`. |
| §8 Sixteen gates, staged cutover | Holds; assignments specified below | Selection before admission is implementable as one route-level branch on `body.extra_search` until gate 10. |
| §9 Test commands | Holds | Baseline 683 + 21 green. |
| §10 Failure matrix | Holds; adds two rows (below) | |
| §11 Durable execution deferral | Holds | No saver or Store installed. `langgraph-checkpoint` arrives transitively only because LangGraph requires it; it is not used. |
| §12 Learning delivery | Holds | Implementation record and study walkthrough are named below. |

## Concrete contracts

### Module layout (`services/api/lab/workflows/`)

No module may import FastAPI or Starlette (`check_engineering.py` enforces this for `lab/` outside `lab/web/`). AnyIO and asyncio are allowed.

| Module | Owns |
| --- | --- |
| `events.py` | `EventSink` (bounded queue wrapper, capacity 8, `send`/`receive`/`drain`/`close`), per-family allowlists of public event `type`s, and `text_fragments(text, max_bytes=8192)`, which splits at UTF-8 character boundaries without materializing a list. |
| `runtime.py` | `invoke_graph(graph, state, *, context, recursion_limit)` (the **only** `ainvoke` call site in `lab/`; wraps the call in `langsmith.tracing_context(enabled=False)`). Also `PublishOnce`, `GraphRun` (owned task, consumer, cancel-and-wait), and `ActiveRuns` (app-lifetime registry for shutdown). |
| `chat.py` | Chat admission and execution graphs, nodes, routers, `RECURSION_LIMIT`s, and the request context type. |
| `chat_publication.py` | Trace recorder and the chat publisher: assistant save, then trace finalization, then the terminal outcome. |
| `summary.py`, `prerequisites.py` | Family graphs. A separate `*_publication.py` is created only if the publisher is a cohesive unit larger than a few functions; no forwarding-only modules. |

Pure evidence helpers in `evidence_turn.py` (`_retained_chunks`, `_checked_images`, `_merge_images`, `_union_chunks`, `_validate_lookup_result`, warnings) move, in a separate mechanical commit with an AST-equality proof, to a cohesive evidence domain module (for example `evidence_result.py`). Nodes import them from there.

### Invocation and privacy

```python
async def invoke_graph(graph, state, *, context, recursion_limit: int) -> dict:
    with langsmith.tracing_context(enabled=False):
        return await graph.ainvoke(state, context=context, config={"recursion_limit": recursion_limit})
```

- `recursion_limit` has no default. Each family defines it as its longest finite path plus a margin of 2. Exceeding it raises `GraphRecursionError`, which the boundary maps to a sanitized error with no retry.
- The owned execution task is created from a coroutine that calls `invoke_graph`. Suppression is therefore set inside the task's copied context, not by a caller outside it.
- An architecture test asserts no `ainvoke`/`astream`/`invoke`/`stream` call on a graph exists in `lab/` outside `runtime.py`, and no `stream_mode`/`astream_events` use.
- A subprocess test sets a hostile LangSmith environment **before import**, spies `socket.connect`, runs a real family graph against fake production interfaces, and asserts zero non-allowed connections. The subprocess avoids LangSmith's `lru_cache` of environment reads.

### Node execution model (added)

Every node and every conditional-edge function is `async def`. A test enumerates each compiled family graph's node and branch callables and asserts they are coroutine functions. Effectful nodes call existing synchronous store functions inline on the event loop, exactly as today. Nodes never use `run_in_executor`.

### State, context, artifacts

- Routing state is a `TypedDict(total=False)` per family: route, stage, small identity/digest fields, counters (`generation_count`, `lookup_count`), provider outcome kind, and publication status. Updates replace values; no reducers.
- The context is one per-request dataclass per family. It holds the capabilities (gateway, store, profile store, retriever/embedder, the shared `model_generation_lock`, runtime-policy path, settings), the captured immutable inputs, the `EventSink`, the observer, `PublishOnce`, and an artifacts holder. Artifacts carry the session, prompt plans, citations, search results and snapshot. Each slot is assigned only by its owning node.
- Compiled graphs are built once in `create_app` (R9) and stored on `AppDeps`. Nothing is created at import.

### Observer

Each family's observer records `content`/`thinking` text **before** `await sink.send(...)` (R7), hidden buffered bytes separately, `first_output` time, invocation-attempt counters, evidence milestones (initial supplied sources after factory success, final plan), provider completion (`model`, `context`), and close errors. Publishers read only the observer and artifacts, never graph return state, because cancelled nodes return nothing.

### `PublishOnce` (amended shielding)

```python
class PublishOnce:
    async def run(self, publish: Callable[[], Awaitable[Outcome]]) -> Outcome:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(publish())
        try:
            return await asyncio.shield(self._task)
        except asyncio.CancelledError:
            await asyncio.wait({self._task})
            raise
```

The first caller decides the content (complete versus incomplete) from the observer at call time. A later caller, usually the finalizer, awaits the same task and receives the same outcome. There is never a second save. The finalizer calls it from Starlette's AnyIO-shielded `on_close`, where AnyIO shielding is valid. Publication functions themselves stay short: store writes and trace writes only, never inference, queue waits or retrieval.

### Execution consumer and terminal events

```text
started-prefix (summary/prerequisites only)
loop:
    getter = sink.receive() as task
    wait FIRST_COMPLETED on {getter, graph_task}
    getter done        -> yield event; continue
    graph_task done    -> cancel getter; yield sink.drain(); break
finally: cancel getter if pending
terminal = outcome from PublishOnce (or finalizer on graph failure) -> yield its public events
```

- Terminal events (`done` and terminal `error`s) are never enqueued. They are emitted by the consumer only after the graph task has **completed** and the publication outcome is known. A node therefore cannot emit `done` before a later node or state update fails.
- Graph task raised: the finalizer runs `PublishOnce` (incomplete), then emits the family's existing generic failure sequence. If success publication had already completed, the saved result is preserved and a truthful error is emitted (new failure row below).
- Graph completed without a publication outcome: error, not success.
- Starting the graph task happens on the first iteration of the response body, as today. A never-consumed response generates nothing; the finalizer publishes the empty incomplete result exactly as the baseline does.

### HTTP adapters and lease

`web/chat.py`, `web/document_map_summaries.py` and `web/prerequisites.py` keep routes and read APIs. Each streaming route calls one family entry point (`admit_*`) that owns early trace and lease acquisition, awaits the admission graph, and on failure persists the preflight trace, releases the lease and re-raises. It returns an admitted handle with `events()` and `finish()`. The route wraps these in the unchanged `FinalizedStreamingResponse(events, on_close=finish)`. The lease is handed to the handle and released in `finish()`'s outer `finally`. `create_app` adds a FastAPI lifespan whose shutdown cancels and awaits `ActiveRuns`.

### Event allowlists

| Family | Queued types | Terminal (consumer-emitted) |
| --- | --- | --- |
| Chat | `token`, `thinking`, `evidence_status` | `done`, `error` |
| Summary | `token`, `thinking` (prefix `started`) | `done`, `error` |
| Prerequisites | `progress` (prefix `started`) | `done`, `error` |

`EventSink.send` rejects types outside its family allowlist with a programming error. Text fragments are capped at 8 KiB. Today the direct answer is one event of up to `MAX_ACTION_BYTES` (80 KiB); after the pivot it is up to ten fragments. Provider tokens are already small. Terminal payload bounds are unchanged: chat citations ≤ `MAX_SOURCE_REFERENCES` (64), summary content ≤ the model's `num_predict`, prerequisite JSON ≤ `MAX_RESPONSE_BYTES` (24,000). They do not pass through the queue.

## Additional failure-matrix rows

| Trigger | Expected result / proof owner |
| --- | --- |
| Cancellation arrives inside the publication call | Publication completes once (`PublishOnce`); finalizer receives the same outcome; no incomplete duplicate. Coder test cancels the graph task mid-publication with a blocking fake store. |
| Hostile inherited LangSmith environment | Zero non-local connections; no tracer handler. Subprocess test (gate 5). |
| Sync callable accidentally added to a graph | Architecture test fails (gate 4 onward). |

## Gate assignments and loop

Gates and order are unchanged from plan §8. Roles for this run follow Tanmay's instruction: research, design, review, testing and usage are performed by the coordinator (main session). Code is delegated to coding sub-agents, one writer per path, in the shared checkout. The configured Codex role models in `.codex/agents/` are not available in Cursor; that is an explicit, user-directed substitution, not a silent one. For each gate:

1. Coordinator issues acceptance criteria, owned paths and these contracts.
2. Coder implements and runs focused tests; reports changed paths and results without Git mutations.
3. Coordinator inspects the diff, reruns focused and full backend tests plus engineering/Ruff checks, and commits (`test:`/`wip:`/`fix:`/`feat:`/`refactor:` as appropriate).
4. If anything fails, the coordinator returns exact failures to the coder (code → test → fix) until the gate's checks pass.
5. Coordinator updates the [implementation record](2026_10_20_langgraph_implementation.md), then pushes `dev` to `origin`. Tanmay authorized pushing tested bite-sized pieces in this request. No force-push; `main` is untouched.

Independent review at gates 5, 10, 14 and 16 and usage verification at 10, 12, 14 and 16 are performed by the coordinator against actual diffs and an isolated launcher.

## Verified versus assumed

Verified by execution: R1–R12 in the research report. Assumed until gates pass: full-suite parity after each cutover, exact error sequences under the new consumer, lock install in the real project environment, real Ollama close timing, and per-token scheduling overhead. If the production disconnect suites fail under the new consumer, or cancellation does not propagate into the lookup child task, the runtime seam is reopened before more product wiring. Credit gating and the pre-response handshake remain the recorded alternatives.
