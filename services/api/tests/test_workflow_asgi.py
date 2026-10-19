"""ASGI disconnect behavior for GraphRun-backed FinalizedStreamingResponse."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import Any, TypedDict

import pytest
from fastapi import FastAPI, Request
from starlette.requests import ClientDisconnect
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from lab.web.middleware import FinalizedStreamingResponse
from lab.workflows.events import EventSink
from lab.workflows.runtime import GraphRun, PublishOnce

_CHAT_TYPES = frozenset({"token"})


class StreamState(TypedDict, total=False):
    out: str


@dataclass
class ProviderCtx:
    sink: EventSink
    accepted: list[str] = field(default_factory=list)
    provider_closed: asyncio.Event = field(default_factory=asyncio.Event)
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    silent: bool = False


async def _token_provider(ctx: ProviderCtx) -> Any:
    try:
        yield "first"
        ctx.entered.set()
        if ctx.silent:
            await asyncio.Event().wait()
        for index in range(10_000):
            await asyncio.sleep(0)
            yield f"t{index}"
    finally:
        ctx.provider_closed.set()


async def _generate_node(_state: StreamState, runtime: Runtime[ProviderCtx]) -> StreamState:
    ctx = runtime.context
    generator = _token_provider(ctx)
    try:
        async for token in generator:
            ctx.accepted.append(token)
            await ctx.sink.send({"type": "token", "text": token})
    finally:
        await generator.aclose()
    return {"out": "done"}


_GRAPH = StateGraph(StreamState, context_schema=ProviderCtx)
_GRAPH.add_node("generate", _generate_node)
_GRAPH.add_edge(START, "generate")
_GRAPH.add_edge("generate", END)
COMPILED = _GRAPH.compile()

_mode_flags: dict[str, bool] = {"silent": False, "publication_raises": False}
_observed: dict[str, Any] = {}


def _build_app(*, http_middleware: bool) -> FastAPI:
    app = FastAPI()

    if http_middleware:

        @app.middleware("http")
        async def passthrough(request: Request, call_next: Any) -> Any:
            return await call_next(request)

    @app.post("/stream")
    async def stream() -> FinalizedStreamingResponse:
        sink = EventSink(allowed_types=_CHAT_TYPES, capacity=8)
        ctx = ProviderCtx(sink=sink, silent=_mode_flags["silent"])
        lease = asyncio.Lock()
        await lease.acquire()
        _observed["lease"] = lease
        publish_once = PublishOnce()
        finish_count = 0

        run = GraphRun(
            graph=COMPILED,
            state={},
            context=ctx,
            recursion_limit=10,
            sink=sink,
        )
        _observed["ctx"] = ctx
        _observed["run"] = run

        async def finish() -> None:
            nonlocal finish_count
            finish_count += 1
            _observed["finish_count"] = finish_count
            await run.cancel_and_wait()

            async def publish() -> str:
                if _mode_flags["publication_raises"]:
                    msg = "publication failed"
                    raise RuntimeError(msg)
                await asyncio.sleep(0.05)
                return "ok"

            try:
                await publish_once.run(publish)
            except RuntimeError:
                pass
            finally:
                if lease.locked():
                    lease.release()

        async def events() -> Any:
            async for event in run.events():
                yield json.dumps(event) + "\n"
            yield json.dumps({"type": "done"}) + "\n"

        return FinalizedStreamingResponse(events(), on_close=finish, media_type="application/x-ndjson")

    return app


def _scope(spec_version: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/stream",
        "raw_path": b"/stream",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"content-length", b"0")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


async def _run_scenario(
    *,
    spec_version: str,
    http_middleware: bool,
    silent: bool,
    slow_reader: bool,
    full_queue: bool,
    disconnect: bool,
) -> None:
    _observed.clear()
    _mode_flags["silent"] = silent
    _mode_flags["publication_raises"] = False
    app = _build_app(http_middleware=http_middleware)
    pending = [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive() -> dict[str, Any]:
        if pending:
            return pending.pop(0)
        if disconnect:
            while "ctx" not in _observed:
                await asyncio.sleep(0.001)
            ctx: ProviderCtx = _observed["ctx"]
            await ctx.entered.wait()
            if full_queue:
                while len(ctx.accepted) < 10:
                    await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            return {"type": "http.disconnect"}
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] != "http.response.body":
            return
        if slow_reader:
            await asyncio.Event().wait()
        if disconnect:
            msg = "simulated disconnect"
            raise OSError(msg)

    task = asyncio.create_task(app(_scope(spec_version), receive, send))
    try:
        await asyncio.wait_for(task, timeout=3)
    except (TimeoutError, OSError, ClientDisconnect):
        if not task.done():
            task.cancel()
    with contextlib.suppress(asyncio.CancelledError, OSError, ClientDisconnect):
        await task
    await asyncio.sleep(0.1)
    ctx: ProviderCtx = _observed["ctx"]
    run: GraphRun = _observed["run"]
    lease: asyncio.Lock = _observed["lease"]
    assert _observed.get("finish_count") == 1
    assert run._task is not None and run._task.done()
    assert ctx.provider_closed.is_set()
    assert len(ctx.accepted) <= 11
    assert not lease.locked()
    leftover = [
        item
        for item in asyncio.all_tasks()
        if item is not asyncio.current_task() and not item.done() and "Queue.get" in repr(item)
    ]
    assert leftover == []


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
@pytest.mark.parametrize("http_middleware", [False, True])
@pytest.mark.parametrize(
    ("silent", "slow_reader", "full_queue"),
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
    ],
)
@pytest.mark.anyio
async def test_asgi_disconnect_finalizes_graph_run(
    spec_version: str,
    http_middleware: bool,
    silent: bool,
    slow_reader: bool,
    full_queue: bool,
) -> None:
    await _run_scenario(
        spec_version=spec_version,
        http_middleware=http_middleware,
        silent=silent,
        slow_reader=slow_reader,
        full_queue=full_queue,
        disconnect=True,
    )


@pytest.mark.anyio
async def test_on_close_releases_lease_when_publication_raises() -> None:
    _observed.clear()
    _mode_flags["silent"] = True
    _mode_flags["publication_raises"] = True
    app = _build_app(http_middleware=False)
    pending = [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive() -> dict[str, Any]:
        if pending:
            return pending.pop(0)
        while "ctx" not in _observed:
            await asyncio.sleep(0.001)
        await _observed["ctx"].entered.wait()
        return {"type": "http.disconnect"}

    async def send(_message: dict[str, Any]) -> None:
        return None

    await app(_scope("2.4"), receive, send)
    lease: asyncio.Lock = _observed["lease"]
    assert _observed.get("finish_count") == 1
    assert not lease.locked()
