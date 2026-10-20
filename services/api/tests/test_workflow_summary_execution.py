"""Gate 12: summary execution LangGraph and publication (real graphs, fake interfaces)."""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest
from lab.errors import CorruptData
from lab.workflows.runtime import GraphRun, PublishOnce
from lab.workflows.summary import (
    SUMMARY_EXECUTION_NODE_NAMES,
    SUMMARY_EXECUTION_RECURSION_LIMIT,
    SummaryExecutionContext,
    compile_summary_execution_graph,
)
from lab.workflows.summary_publication import SummaryObserver, SummaryPublicationBundle
from lab.workflows.events import EventSink
from tests.test_document_map_summaries_api import (
    BlockingSummaryModel,
    SummaryFakeModel,
    _client,
    _events,
    _summary_url,
)
from tests.workflow_graph_introspection import draw_mermaid, graph_callables, graph_edge_set


def _patch_summary_writes(monkeypatch, replacement) -> None:
    import lab.workflows.summary as summary_workflow
    import lab.workflows.summary_publication as summary_publication

    monkeypatch.setattr(summary_workflow, "write_summary_attempt", replacement)
    monkeypatch.setattr(summary_publication, "write_summary_attempt", replacement)


# Documented in docs/workflows.md: stream_summary -. success .-> validate_and_publish; failure .-> publish_failure
SUMMARY_EXECUTION_EDGES = frozenset(
    {
        ("__start__", "stream_summary", None, False),
        ("stream_summary", "validate_and_publish", None, True),
        ("stream_summary", "publish_failure", None, True),
        ("validate_and_publish", "__end__", None, False),
        ("publish_failure", "__end__", None, False),
    }
)


def test_summary_execution_mermaid_contains_node_names() -> None:
    compiled = compile_summary_execution_graph()
    text = draw_mermaid(compiled)
    for name in SUMMARY_EXECUTION_NODE_NAMES:
        assert name in text
    assert graph_edge_set(compiled) == SUMMARY_EXECUTION_EDGES
    assert SUMMARY_EXECUTION_RECURSION_LIMIT == len(SUMMARY_EXECUTION_NODE_NAMES) + 2


def test_summary_execution_graph_callables_are_coroutines() -> None:
    compiled = compile_summary_execution_graph()
    node_funcs = {name.removeprefix("node:"): fn for name, fn in graph_callables(compiled) if name.startswith("node:")}
    for name in SUMMARY_EXECUTION_NODE_NAMES:
        func = node_funcs[name]
        assert func is not None, name
        assert inspect.iscoroutinefunction(func), name
    from lab.workflows import summary as summary_module

    assert inspect.iscoroutinefunction(summary_module._route_after_stream)


def test_execution_success_sequence_and_persistence(tmp_path) -> None:
    client, _, topic, outline, model = _client(tmp_path)
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )
    assert response.status_code == 200
    events = _events(response)
    assert [event["type"] for event in events] == ["started", "thinking", "token", "done"]
    assert len(model.summary_requests) == 1
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"]["status"] == "completed"
    assert saved["last_summary"]["content"] == "A synthetic statement [S1]."


@pytest.mark.parametrize(
    ("behavior", "output", "terminal_message"),
    [
        ("error", "A synthetic statement [S1].", "synthetic provider failure"),
        ("eof", "A synthetic statement [S1].", "The model stream ended before completion."),
        (
            "done",
            "Supported [S1], fabricated [S0].",
            "The summary contains a malformed source label; retry the summary.",
        ),
    ],
)
def test_execution_stream_faults(tmp_path, behavior, output, terminal_message) -> None:
    model = SummaryFakeModel(output=output, behavior=behavior)
    client, _, topic, outline, _ = _client(tmp_path, model=model)
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )
    events = _events(response)
    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == terminal_message
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"]["status"] == "error"
    assert saved["last_summary"] is None


def test_execution_prior_success_survives_failed_regeneration(tmp_path) -> None:
    model = SummaryFakeModel()
    client, _, topic, outline, _ = _client(tmp_path, model=model)
    url = _summary_url(topic, outline["revision"], outline["sections"][0]["id"])
    body = {"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None}
    assert _events(client.post(url, json=body))[-1]["type"] == "done"
    model.output = "Replacement without citations."
    assert _events(client.post(url, json=body))[-1]["type"] == "error"
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["last_summary"]["content"] == "A synthetic statement [S1]."


def test_execution_map_revision_check_before_publication(tmp_path) -> None:
    from tests.test_workflow_characterization import _RevisionChangeSummaryModel

    client, store, topic, outline, _ = _client(tmp_path)
    client.app.state.deps.model_backend = _RevisionChangeSummaryModel(store, topic)
    response = client.post(
        _summary_url(topic, outline["revision"], outline["sections"][0]["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )
    events = _events(response)
    assert events[-1]["message"] == "The source document changed while the summary was generating."
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"]["status"] == "interrupted"
    assert saved["last_summary"] is None


def test_execution_save_before_done_event(tmp_path, monkeypatch) -> None:
    from lab.document_map_summary_store import write_summary_attempt

    client, _, topic, outline, _ = _client(tmp_path)
    seen: list[str] = []

    def tracking_write(store, write_topic, file_id, attempt, *, summary=None):
        if summary is not None:
            seen.append("summary")
        return write_summary_attempt(store, write_topic, file_id, attempt, summary=summary)

    _patch_summary_writes(monkeypatch, tracking_write)
    response = client.post(
        _summary_url(topic, outline["revision"], outline["sections"][0]["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )
    events = _events(response)
    assert events[-1]["type"] == "done"
    assert seen == ["summary"]


def test_execution_terminal_write_failure_never_emits_done(tmp_path, monkeypatch) -> None:
    from lab.document_map_summary_store import write_summary_attempt

    client, _, topic, outline, model = _client(tmp_path)

    def fail_summary_write(store, write_topic, file_id, attempt, *, summary=None):
        if summary is not None:
            raise CorruptData("synthetic durable write failure")
        return write_summary_attempt(store, write_topic, file_id, attempt)

    _patch_summary_writes(monkeypatch, fail_summary_write)
    response = client.post(
        _summary_url(topic, outline["revision"], outline["sections"][0]["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )
    events = _events(response)
    assert events[-1]["type"] == "error"
    assert all(event["type"] != "done" for event in events)
    assert len(model.summary_requests) == 1


@pytest.mark.anyio
async def test_execution_cancel_during_running_stream_preserves_prior_success(tmp_path) -> None:
    import lab.web.document_map_summaries as summary_routes
    from lab.web.schemas import SectionSummaryInput

    model = SummaryFakeModel()
    client, _, topic, outline, _ = _client(tmp_path, model=model)
    url = _summary_url(topic, outline["revision"], outline["sections"][0]["id"])
    body = {"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None}
    assert _events(client.post(url, json=body))[-1]["type"] == "done"

    blocking = BlockingSummaryModel()
    client.app.state.deps.model_backend = blocking
    deps = client.app.state.deps
    endpoint = summary_routes.router(deps).routes[0].endpoint
    section = outline["sections"][0]
    token_sent = asyncio.Event()

    async def scenario() -> None:
        response = await endpoint(
            topic,
            "paper-1",
            section["id"],
            SectionSummaryInput(revision=outline["revision"], model="fake", context_limit=8192, think=None),
        )

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.body" and b"Partial finding" in message.get("body", b""):
                token_sent.set()

        task = asyncio.create_task(
            response(
                {"type": "http", "asgi": {"spec_version": "2.4"}, "method": "POST", "path": "/summary", "headers": []},
                receive,
                send,
            )
        )
        await asyncio.wait_for(blocking.stream_requested.wait(), timeout=1)
        await asyncio.wait_for(token_sent.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    await scenario()
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["last_summary"]["content"] == "A synthetic statement [S1]."
    assert saved["latest_attempt"]["status"] == "cancelled"


@pytest.mark.anyio
async def test_cancel_after_provider_done_finishes_summary_attempt(tmp_path, monkeypatch) -> None:
    import lab.web.document_map_summaries as summary_routes
    import lab.workflows.summary as summary_workflow
    from lab.web.schemas import SectionSummaryInput

    route_arrived = asyncio.Event()

    async def blocked_route(_state):
        route_arrived.set()
        await asyncio.Event().wait()
        return "validate_and_publish"

    monkeypatch.setattr(summary_workflow, "_route_after_stream", blocked_route)
    client, store, topic, outline, _ = _client(tmp_path)
    deps = client.app.state.deps
    endpoint = summary_routes.router(deps).routes[0].endpoint
    section = outline["sections"][0]
    response = await endpoint(
        topic,
        "paper-1",
        section["id"],
        SectionSummaryInput(revision=outline["revision"], model="fake", context_limit=8192),
    )

    async def consume_response():
        return [line async for line in response.body_iterator]

    consumer = asyncio.create_task(consume_response())
    await asyncio.wait_for(route_arrived.wait(), timeout=1)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(consumer, timeout=1)

    saved = json.loads(store.file_path(topic, "paper-1.map.json").read_text())["sections"][0]
    assert not deps.locks[topic].locked()
    assert not deps.active_document_map_summaries
    assert saved["latest_attempt"]["status"] == "cancelled", saved["latest_attempt"]


@pytest.mark.anyio
async def test_publish_once_completed_not_overwritten_by_cancelled() -> None:
    from lab.workflows.summary_publication import publish_summary_cancelled

    publish_once: PublishOnce = PublishOnce()
    bundle = SummaryPublicationBundle(
        store=object(),
        topic="t",
        file_id="f",
        section_id="s",
        expected_revision="0" * 64,
        attempt_id="a",
        base_attempt={"id": "a", "status": "generating", "content": "x"},
        plan={"section": {"title": "T"}, "sources": []},
        requested_model="fake",
        context_limit=8192,
        think=None,
    )
    observer = SummaryObserver()
    observer.mark_completed(model="fake")

    async def publish_success() -> object:
        from lab.workflows.summary_publication import SummaryPublicationOutcome

        return SummaryPublicationOutcome(
            terminal_persisted=True,
            terminal_events=[{"type": "done", "attempt_id": "a"}],
        )

    first = await publish_once.run(publish_success)

    async def publish_cancel() -> object:
        return await publish_summary_cancelled(bundle, observer)

    second = await publish_once.run(publish_cancel)
    assert first.terminal_events[0]["type"] == "done"
    assert second.terminal_events[0]["type"] == "done"


@pytest.mark.anyio
async def test_execution_slow_consumer_backpressure_and_no_queue_leaks() -> None:
    from langgraph.graph import END, START, StateGraph
    from langgraph.runtime import Runtime

    from lab.workflows.summary import SUMMARY_STREAM_EVENT_TYPES

    class State(dict):
        pass

    async def flood(_state, runtime: Runtime) -> State:
        ctx = runtime.context
        for index in range(20):
            await ctx.sink.send({"type": "token", "attempt_id": "a", "text": f"t{index}"})
        return {"route": "failure"}

    builder = StateGraph(State)
    builder.add_node("flood", flood)
    builder.add_edge(START, "flood")
    builder.add_edge("flood", END)
    compiled = builder.compile()
    sink = EventSink(allowed_types=SUMMARY_STREAM_EVENT_TYPES, capacity=8)
    publish_once: PublishOnce = PublishOnce()
    bundle = SummaryPublicationBundle(
        store=object(),
        topic="t",
        file_id="f",
        section_id="s",
        expected_revision="0" * 64,
        attempt_id="a",
        base_attempt={"id": "a", "status": "generating"},
        plan={"section": {"title": "T"}, "sources": []},
        requested_model="fake",
        context_limit=8192,
        think=None,
    )
    ctx = SummaryExecutionContext(
        model_backend=object(),
        generation_lock=asyncio.Lock(),
        bundle=bundle,
        observer=SummaryObserver(),
        sink=sink,
        publish_once=publish_once,
        plan_messages=[],
        prompt_context={},
        requested_model="fake",
        think=None,
        context_limit=8192,
    )
    run = GraphRun(graph=compiled, state={}, context=ctx, recursion_limit=5, sink=sink)
    task = asyncio.create_task(run.result())
    await asyncio.sleep(0.05)
    await run.cancel_and_wait()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)
    leaked = [
        item
        for item in asyncio.all_tasks()
        if item is not asyncio.current_task() and not item.done() and "Queue.get" in repr(item)
    ]
    assert leaked == []
