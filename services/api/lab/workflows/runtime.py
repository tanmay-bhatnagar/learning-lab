"""Graph invocation, publication latch, and owned run lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, TypeVar

import langsmith
from langgraph.graph.state import CompiledStateGraph

from lab.workflows.events import EventSink

OutcomeT = TypeVar("OutcomeT")


async def invoke_graph(
    graph: CompiledStateGraph[Any, Any, Any, Any],
    state: Mapping[str, Any],
    *,
    context: object,
    recursion_limit: int,
) -> dict[str, Any]:
    """Invoke a compiled LangGraph with tracing disabled (sole ``ainvoke`` site in ``lab/``)."""
    with langsmith.tracing_context(enabled=False):
        return await graph.ainvoke(
            state,
            context=context,
            config={"recursion_limit": recursion_limit},
        )


class PublishOnce:
    """Run a publication coroutine once; shield callers and finish on cancellation."""

    def __init__(self) -> None:
        self._task: asyncio.Task[OutcomeT] | None = None

    async def run(self, publish: Callable[[], Awaitable[OutcomeT]]) -> OutcomeT:
        """Await the single publication task, creating it on first call."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(publish())
        try:
            return await asyncio.shield(self._task)
        except asyncio.CancelledError:
            await asyncio.wait({self._task})
            raise


class GraphRun:
    """One graph execution task and a sink consumer that avoids queue getter leaks."""

    def __init__(
        self,
        *,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        state: Mapping[str, Any],
        context: object,
        recursion_limit: int,
        sink: EventSink,
        terminal_events: Callable[[dict[str, Any] | None, BaseException | None], AsyncIterator[Mapping[str, Any]]]
        | None = None,
    ) -> None:
        self._graph = graph
        self._state = state
        self._context = context
        self._recursion_limit = recursion_limit
        self._sink = sink
        self._terminal_events = terminal_events
        self._task: asyncio.Task[dict[str, Any]] | None = None
        self._finished_exception: BaseException | None = None
        self._result: dict[str, Any] | None = None
        self._cancelled = False

    async def _execute(self) -> dict[str, Any]:
        try:
            self._result = await invoke_graph(
                self._graph,
                self._state,
                context=self._context,
                recursion_limit=self._recursion_limit,
            )
        except BaseException as exc:
            self._finished_exception = exc
            raise
        return self._result

    def _ensure_task(self) -> asyncio.Task[dict[str, Any]]:
        if self._task is None:
            self._task = asyncio.create_task(self._execute())
        return self._task

    async def events(self) -> AsyncIterator[Mapping[str, Any]]:
        """Yield queued graph events, then terminal events after the graph task completes."""
        task = self._ensure_task()
        getter: asyncio.Task[Mapping[str, Any]] | None = None
        try:
            while True:
                getter = asyncio.ensure_future(self._sink.receive())
                done, _pending = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    yield getter.result()
                    getter = None
                    continue
                getter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await getter
                getter = None
                for event in self._sink.drain():
                    yield event
                break
        finally:
            if getter is not None and not getter.done():
                getter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await getter

        outcome: dict[str, Any] | None = None
        error: BaseException | None = None
        if task.done():
            if task.cancelled():
                error = asyncio.CancelledError()
            else:
                with contextlib.suppress(asyncio.CancelledError):
                    try:
                        outcome = task.result()
                    except BaseException as exc:  # noqa: BLE001 - surface graph task failure to terminal handler
                        error = exc
        if self._terminal_events is not None:
            async for terminal in self._terminal_events(outcome, error):
                yield terminal

    async def result(self) -> dict[str, Any]:
        """Return the graph output after awaiting completion."""
        task = self._ensure_task()
        return await asyncio.shield(task)

    def exception(self) -> BaseException | None:
        """Return a stored failure without awaiting."""
        if self._finished_exception is not None:
            return self._finished_exception
        if self._task is not None and self._task.done() and not self._task.cancelled():
            with contextlib.suppress(asyncio.CancelledError):
                self._task.result()
        return self._finished_exception

    async def cancel_and_wait(self) -> None:
        """Cancel the execution task and await it; safe to call repeatedly."""
        if self._cancelled and (self._task is None or self._task.done()):
            return
        self._cancelled = True
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task


class ActiveRuns:
    """App-lifetime registry of in-flight graph runs for shutdown cancellation."""

    def __init__(self) -> None:
        self._runs: set[GraphRun] = set()

    def register(self, run: GraphRun) -> None:
        self._runs.add(run)

    def unregister(self, run: GraphRun) -> None:
        self._runs.discard(run)

    async def cancel_all(self) -> None:
        runs = list(self._runs)
        await asyncio.gather(*(run.cancel_and_wait() for run in runs), return_exceptions=True)
