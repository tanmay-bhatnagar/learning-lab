"""Gate 7: ordinary chat execution graph and publication."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lab.config import load_config
from lab.profile_store import ProfileStore
from lab.profile_parse import parse_profile_pdf
from lab.storage import Store
from lab.web.chat import router as chat_router
from lab.web.conversations import router as conversations_router
from lab.web.deps import AppDeps
from lab.web.topics import router as topics_router
from lab.workflows.chat import EXECUTION_RECURSION_LIMIT, build_chat_graphs, execution_graph_callables
from lab.workflows.chat_publication import ChatPublicationOutcome, emit_late_graph_failure
from lab.workflows.events import EventSink
from lab.workflows.runtime import GraphRun
from tests.fakes import FakeModel
from tests.test_query_traces import payload


def _chat_app(tmp_path, model=None):
    cfg = load_config(learning_root=tmp_path / "Learning", settings_path=tmp_path / "settings.json")
    store = Store(cfg.learning_root, cfg.settings_path)
    profile_store = ProfileStore(cfg.profile_root)
    deps = AppDeps(
        store=store,
        profile_store=profile_store,
        profile_parser=parse_profile_pdf,
        config=cfg,
        model_backend=model or FakeModel(token_text="hello world"),
    )
    app = FastAPI()
    app.state.deps = deps
    app.include_router(topics_router(deps))
    app.include_router(conversations_router(deps))
    app.include_router(chat_router(deps))
    return app


def _events(response) -> list[dict[str, Any]]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_execution_graph_callables_are_async():
    graphs = build_chat_graphs()
    for name, fn in execution_graph_callables(graphs.execution):
        assert inspect.iscoroutinefunction(fn), name


def test_execution_mermaid_contains_stream_and_publish():
    mermaid = build_chat_graphs().execution.get_graph().draw_mermaid()
    assert "stream_answer" in mermaid
    assert "publish" in mermaid


def test_recursion_limit_constant():
    assert EXECUTION_RECURSION_LIMIT >= 4


def test_default_route_one_stream_call_and_token_concatenation(tmp_path):
    model = FakeModel(token_text="hello world")
    client = TestClient(_chat_app(tmp_path, model))
    topic = client.post("/api/topics", json={"name": "Ordinary"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 200
    events = _events(response)
    assert events[-1]["type"] == "done"
    tokens = "".join(event.get("text", "") for event in events if event.get("type") == "token")
    assert tokens == "hello world"
    assert len(model.calls) == 1


def test_named_conversation_route(tmp_path):
    client = TestClient(_chat_app(tmp_path))
    topic = client.post("/api/topics", json={"name": "Named"}).json()["id"]
    conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "C"}).json()["id"]
    response = client.post(
        f"/api/topics/{topic}/conversations/{conversation}/chat",
        json=payload(message="Named turn"),
    )
    assert response.status_code == 200
    assert _events(response)[-1]["type"] == "done"


def test_provider_error_saves_incomplete_assistant(tmp_path):
    class ErrorEventModel(FakeModel):
        async def stream_chat(self, messages, model, think, context_limit, context_metadata=None, *, generation_lock):
            self.calls.append(messages)
            async with generation_lock:
                yield {"type": "token", "text": "partial"}
                yield {"type": "error", "message": "provider broke"}

    client = TestClient(_chat_app(tmp_path, ErrorEventModel()))
    topic = client.post("/api/topics", json={"name": "Provider error"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    events = _events(response)
    assert events[-1]["type"] == "error"
    session = client.get(f"/api/topics/{topic}/messages").json()
    assert session["messages"][-1].get("incomplete") is True
    assert session["messages"][-1]["content"] == "partial"


def test_premature_eof_saves_partial(tmp_path):
    class EofModel(FakeModel):
        async def stream_chat(self, messages, model, think, context_limit, context_metadata=None, *, generation_lock):
            self.calls.append(messages)
            async with generation_lock:
                yield {"type": "token", "text": "partial without done"}

    client = TestClient(_chat_app(tmp_path, EofModel()))
    topic = client.post("/api/topics", json={"name": "EOF"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert _events(response)[-1]["type"] == "error"
    assert client.get(f"/api/topics/{topic}/messages").json()["messages"][-1]["content"] == "partial without done"


def test_generation_exception_saves_partial(tmp_path):
    client = TestClient(_chat_app(tmp_path, FakeModel(fail=True, token_text="partial")))
    topic = client.post("/api/topics", json={"name": "Exception"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert _events(response)[-1]["type"] == "error"
    messages = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert messages[-1].get("incomplete") is True
    assert "partial" in messages[-1]["content"]


def test_save_before_trace_on_success(tmp_path):
    client = TestClient(_chat_app(tmp_path))
    topic = client.post("/api/topics", json={"name": "Trace order"}).json()["id"]
    client.post(f"/api/topics/{topic}/chat", json=payload())
    from lab.query_traces import list_traces, trace_path

    trace = list_traces(trace_path(client.app.state.deps.store.topic(topic)), conversation_id="default", limit=1)[0]
    assert trace["assistant_saved"] is True
    assert trace["status"] == "completed"


def test_trace_finalize_failure_preserves_answer_without_done(tmp_path, monkeypatch):
    import lab.web.chat as chat_module

    def fail_finalize(*_args, **_kwargs):
        raise RuntimeError("trace store down")

    monkeypatch.setattr(chat_module, "finalize_trace", fail_finalize)
    client = TestClient(_chat_app(tmp_path))
    topic = client.post("/api/topics", json={"name": "Trace fail"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    events = _events(response)
    assert events[-1]["type"] == "error"
    assert "trace could not be finalized" in events[-1]["message"]
    assert not any(event.get("type") == "done" for event in events)
    messages = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1].get("incomplete") is not True
    assert len([message for message in messages if message["role"] == "assistant"]) == 1


@pytest.mark.anyio
async def test_late_graph_failure_after_publication_emits_error_without_duplicate_save():
    publication = ChatPublicationOutcome(
        complete=True,
        published=True,
        assistant_saved=True,
        terminal_events=[{"type": "done", "model": "fake"}],
    )
    events = [item async for item in emit_late_graph_failure(publication=publication, graph_error=RuntimeError("late"))]
    assert len(events) == 1
    assert events[0]["type"] == "error"


@pytest.mark.anyio
async def test_slow_consumer_bounds_producer():
    from langgraph.graph import END, START, StateGraph
    from langgraph.runtime import Runtime
    from typing import TypedDict

    class State(TypedDict, total=False):
        pass

    class Ctx:
        def __init__(self, sink: EventSink):
            self.sink = sink

    async def flood(_state: State, runtime: Runtime[Ctx]) -> State:
        for index in range(32):
            await runtime.context.sink.send({"type": "token", "text": f"t{index}"})
        return {}

    builder = StateGraph(State, context_schema=Ctx)
    builder.add_node("flood", flood)
    builder.add_edge(START, "flood")
    builder.add_edge("flood", END)
    compiled = builder.compile()
    sink = EventSink(allowed_types=frozenset({"token"}), capacity=8)
    run = GraphRun(graph=compiled, state={}, context=Ctx(sink), recursion_limit=5, sink=sink)
    count = 0
    async for _event in run.events():
        count += 1
        if count == 3:
            await run.cancel_and_wait()
            break
    assert count >= 3
