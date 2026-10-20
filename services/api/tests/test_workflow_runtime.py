"""Runtime seam tests with real LangGraph graphs (no LangGraph mocking)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, TypedDict, get_type_hints

import pytest
from fastapi.testclient import TestClient
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from lab.web.app import create_app
from lab.workflows.events import EventSink
from lab.workflows.runtime import GraphRun, PublishOnce, invoke_graph

_CHAT_TYPES = frozenset({"token"})


class CounterState(TypedDict, total=False):
    n: int
    out: str


@dataclass
class StreamCtx:
    sink: EventSink
    accepted: list[str] = field(default_factory=list)
    provider_closed: asyncio.Event = field(default_factory=asyncio.Event)
    hold: asyncio.Event | None = None
    gate: asyncio.Lock | None = None
    entered: asyncio.Event | None = None


async def _provider(ctx: StreamCtx, count: int) -> Any:
    try:
        for index in range(count):
            await asyncio.sleep(0)
            yield f"t{index}"
    finally:
        ctx.provider_closed.set()


async def _stream_node(state: CounterState, runtime: Runtime[StreamCtx]) -> CounterState:
    ctx = runtime.context
    if ctx.hold is not None:
        ctx.hold.set()
        await asyncio.Event().wait()
    count = state.get("n", 10)
    generator = _provider(ctx, count)
    try:
        async for token in generator:
            ctx.accepted.append(token)
            await ctx.sink.send({"type": "token", "text": token})
    finally:
        await generator.aclose()
    return {"out": "done"}


async def _lock_node(_state: CounterState, runtime: Runtime[StreamCtx]) -> CounterState:
    ctx = runtime.context
    if ctx.entered is not None:
        ctx.entered.set()
    assert ctx.gate is not None
    await ctx.gate.acquire()
    return {"out": "locked"}


async def _boom_node(_state: CounterState, runtime: Runtime[StreamCtx]) -> CounterState:
    del runtime
    raise LookupError("domain failure")


def _stream_graph() -> Any:
    graph = StateGraph(CounterState, context_schema=StreamCtx)
    graph.add_node("stream", _stream_node)
    graph.add_node("lock", _lock_node)
    graph.add_node("boom", _boom_node)
    graph.add_conditional_edges(
        START,
        lambda state: state.get("route", "stream"),
        {"stream": "stream", "lock": "lock", "boom": "boom"},
    )
    graph.add_edge("stream", END)
    graph.add_edge("lock", END)
    graph.add_edge("boom", END)
    return graph.compile()


GRAPH = _stream_graph()


def test_workflow_public_execution_type_hints_resolve_publication_latches() -> None:
    from lab.workflows.prerequisites import PrerequisiteExecutionHandle, PrerequisitePublicationOutcome
    from lab.workflows.summary import SummaryExecutionContext, SummaryPublicationOutcome

    summary_hints = get_type_hints(SummaryExecutionContext)
    prerequisite_hints = get_type_hints(PrerequisiteExecutionHandle)

    assert summary_hints["publish_once"] == PublishOnce[SummaryPublicationOutcome]
    assert prerequisite_hints["publish_once"] == PublishOnce[PrerequisitePublicationOutcome]


def _leaked_queue_get_tasks() -> list[asyncio.Task[object]]:
    return [
        item
        for item in asyncio.all_tasks()
        if item is not asyncio.current_task() and not item.done() and "Queue.get" in repr(item)
    ]


async def _terminal_events(
    outcome: dict[str, Any] | None,
    error: BaseException | None,
) -> Any:
    if error is not None:
        yield {"type": "error", "detail": type(error).__name__}
    else:
        yield {"type": "done", "out": outcome.get("out") if outcome else None}


@pytest.mark.anyio
async def test_consumer_drains_queue_then_emits_terminal() -> None:
    sink = EventSink(allowed_types=_CHAT_TYPES, capacity=8)
    ctx = StreamCtx(sink=sink)
    run = GraphRun(
        graph=GRAPH,
        state={"route": "stream", "n": 5},
        context=ctx,
        recursion_limit=10,
        sink=sink,
        terminal_events=_terminal_events,
    )
    seen: list[dict[str, Any]] = []
    async for event in run.events():
        seen.append(dict(event))
    assert [event["type"] for event in seen[:5]] == ["token"] * 5
    assert seen[-1]["type"] == "done"
    assert (await run.result())["out"] == "done"


@pytest.mark.anyio
async def test_cancel_while_blocked_on_full_sink() -> None:
    sink = EventSink(allowed_types=_CHAT_TYPES, capacity=8)
    ctx = StreamCtx(sink=sink)
    run = GraphRun(
        graph=GRAPH,
        state={"route": "stream", "n": 100},
        context=ctx,
        recursion_limit=10,
        sink=sink,
    )
    task = asyncio.create_task(run.result())
    await asyncio.sleep(0.05)
    await run.cancel_and_wait()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ctx.provider_closed.is_set()
    await asyncio.sleep(0.05)
    assert _leaked_queue_get_tasks() == []


@pytest.mark.anyio
async def test_cancel_while_blocked_on_lock() -> None:
    sink = EventSink(allowed_types=_CHAT_TYPES)
    gate = asyncio.Lock()
    await gate.acquire()
    entered = asyncio.Event()
    ctx = StreamCtx(sink=sink, gate=gate, entered=entered)
    run = GraphRun(
        graph=GRAPH,
        state={"route": "lock"},
        context=ctx,
        recursion_limit=10,
        sink=sink,
    )
    task = asyncio.create_task(run.result())
    await entered.wait()
    await run.cancel_and_wait()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)
    assert _leaked_queue_get_tasks() == []


@pytest.mark.anyio
async def test_publish_once_completes_under_cancellation_and_reuses_outcome() -> None:
    latch = PublishOnce()
    started = asyncio.Event()
    outcome_box: list[str] = []

    async def publish() -> str:
        started.set()
        await asyncio.sleep(0.2)
        return "published"

    caller = asyncio.create_task(latch.run(publish))
    await started.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    second = await latch.run(publish)
    assert second == "published"
    outcome_box.append(second)
    third = await latch.run(publish)
    assert third == "published"
    assert outcome_box == ["published"]


@pytest.mark.anyio
async def test_node_exception_preserves_type() -> None:
    sink = EventSink(allowed_types=_CHAT_TYPES)
    ctx = StreamCtx(sink=sink)
    run = GraphRun(
        graph=GRAPH,
        state={"route": "boom"},
        context=ctx,
        recursion_limit=10,
        sink=sink,
    )
    with pytest.raises(LookupError, match="domain failure"):
        await run.result()


@pytest.mark.anyio
async def test_explicit_recursion_limit_raises() -> None:
    loop_graph_builder = StateGraph(CounterState)

    async def increment(state: CounterState) -> CounterState:
        return {"n": state.get("n", 0) + 1}

    loop_graph_builder.add_node("loop", increment)
    loop_graph_builder.add_edge(START, "loop")
    loop_graph_builder.add_conditional_edges("loop", lambda state: "loop" if state["n"] < 100 else END)
    loop = loop_graph_builder.compile()
    with pytest.raises(GraphRecursionError):
        await invoke_graph(loop, {"n": 0}, context=None, recursion_limit=5)


def test_compiled_graph_safe_across_asyncio_run_loops() -> None:
    async def once() -> dict[str, Any]:
        sink = EventSink(allowed_types=_CHAT_TYPES)
        ctx = StreamCtx(sink=sink)
        return await invoke_graph(GRAPH, {"route": "stream", "n": 2}, context=ctx, recursion_limit=10)

    first = asyncio.run(once())
    second = asyncio.run(once())
    assert first["out"] == "done"
    assert second["out"] == "done"


def test_app_lifespan_shutdown_cancels_active_run(tmp_path: Any) -> None:
    import json
    import threading
    import time

    app = create_app(tmp_path / "Learning", tmp_path / "state/settings.json")
    deps = app.state.deps
    entered = asyncio.Event()
    run_box: list[GraphRun] = []

    class WaitState(TypedDict, total=False):
        pass

    async def wait_forever(_state: WaitState, runtime: Runtime[StreamCtx]) -> WaitState:
        runtime.context.entered.set()
        await asyncio.Event().wait()
        return {}

    wait_graph = StateGraph(WaitState, context_schema=StreamCtx)
    wait_graph.add_node("wait", wait_forever)
    wait_graph.add_edge(START, "wait")
    wait_graph.add_edge("wait", END)
    compiled = wait_graph.compile()

    @app.post("/__workflow_lifespan_hold")
    async def hold_stream() -> Any:
        sink = EventSink(allowed_types=_CHAT_TYPES)
        ctx = StreamCtx(sink=sink, entered=entered)
        run = GraphRun(
            graph=compiled,
            state={},
            context=ctx,
            recursion_limit=5,
            sink=sink,
        )
        run_box.append(run)
        deps.active_runs.register(run)

        async def body() -> Any:
            try:
                async for event in run.events():
                    yield json.dumps(event) + "\n"
            finally:
                deps.active_runs.unregister(run)

        async def finish() -> None:
            await run.cancel_and_wait()

        from lab.web.middleware import FinalizedStreamingResponse

        return FinalizedStreamingResponse(body(), on_close=finish, media_type="application/x-ndjson")

    def consume_stream(client: TestClient) -> None:
        with client.stream("POST", "/__workflow_lifespan_hold") as response:
            for _line in response.iter_lines():
                if _line:
                    break

    with TestClient(app) as client:
        thread = threading.Thread(target=consume_stream, args=(client,))
        thread.start()
        for _ in range(200):
            if entered.is_set() and run_box:
                break
            time.sleep(0.01)
        assert entered.is_set()
        run = run_box[0]
        assert run._task is not None
        assert not run._task.done()
    thread.join(timeout=5)
    assert run._task.done()
