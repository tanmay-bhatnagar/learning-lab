"""Gate 6: chat admission LangGraph contracts."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lab.errors import DoesNotFit
from lab.web.app import create_app
from lab.web.locks import acquire_topic_lock
from lab.workflows.chat import ADMISSION_RECURSION_LIMIT, build_chat_graphs
from tests.workflow_graph_introspection import graph_callables
from lab.workflows.events import EventSink
from lab.workflows.runtime import GraphRun
from tests.fakes import FakeModel
from tests.test_evidence_chat import _structured_parser
from tests.test_query_traces import payload


class _NoStreamChatModel(FakeModel):
    async def stream_chat(self, *args, **kwargs):
        raise AssertionError("stream_chat must not run during admission")
        yield {"type": "token", "text": ""}  # pragma: no cover - makes this an async generator


class _SpyProfileStore:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.cv_reads: list[str] = []

    def __getattr__(self, name: str) -> Any:
        if name in {"read_extracted_text", "read_profile"}:

            def tracked(*args, **kwargs):
                self.cv_reads.append(name)
                return getattr(self._inner, name)(*args, **kwargs)

            return tracked
        return getattr(self._inner, name)


def _client(tmp_path, *, model=None, profile_root=None, admission_only: bool = False) -> TestClient:
    root = tmp_path / "Learning"
    backend = model if model is not None else (_NoStreamChatModel() if admission_only else FakeModel())
    app = create_app(
        root,
        tmp_path / "settings.json",
        model_backend=backend,
        structured_parser=_structured_parser,
        profile_root=profile_root or tmp_path / "Profile",
    )
    return TestClient(app)


def test_early_missing_attachment_default_route_no_user_no_stream_headers(tmp_path):
    client = _client(tmp_path, admission_only=True)
    topic = client.post("/api/topics", json={"name": "Early error"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload(file_ids=["missing"]))
    assert response.status_code == 404
    assert response.headers.get("content-type", "").startswith("application/x-ndjson") is False
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["user_saved"] is False


def test_early_missing_attachment_named_route(tmp_path):
    client = _client(tmp_path, admission_only=True)
    topic = client.post("/api/topics", json={"name": "Named early"}).json()["id"]
    conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "Named"}).json()["id"]
    response = client.post(
        f"/api/topics/{topic}/conversations/{conversation}/chat",
        json=payload(file_ids=["missing"]),
    )
    assert response.status_code == 404
    trace = client.get(
        f"/api/topics/{topic}/query-traces",
        params={"conversation_id": conversation},
    ).json()["traces"][0]
    assert trace["user_saved"] is False


def test_busy_topic_rejected_before_lease_with_trace(tmp_path):
    app = create_app(tmp_path / "Learning", tmp_path / "settings.json", model_backend=_NoStreamChatModel())
    topic = app.state.deps.store.create("Busy")["id"]

    async def hold():
        return await acquire_topic_lock(app.state.deps.locks, topic)

    lease = asyncio.run(hold())
    try:
        response = TestClient(app).post(f"/api/topics/{topic}/chat", json=payload())
    finally:
        lease.release()
    assert response.status_code == 409
    rows = TestClient(app).get(f"/api/topics/{topic}/query-traces").json()["traces"]
    assert rows[0]["error"]["code"] == "topic_busy"
    assert rows[0]["user_saved"] is False


def test_extra_search_zero_indexed_refuses_without_user(tmp_path):
    client = _client(tmp_path, admission_only=True)
    topic = client.post("/api/topics", json={"name": "Extra zero"}).json()["id"]
    uploaded = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("notes.pdf", b"%PDF-1.7\nunindexed only", "application/pdf")},
        data={"parser": "markitdown"},
    )
    assert uploaded.status_code == 201
    record = uploaded.json()
    assert record.get("index_status") != "ready"
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={**payload(), "extra_search": True, "file_ids": [record["id"]]},
    )
    assert response.status_code == 400
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["user_saved"] is False


def test_cv_off_performs_no_cv_registry_reads(tmp_path):
    client = _client(tmp_path)
    app = client.app
    spy = _SpyProfileStore(app.state.deps.profile_store)
    app.state.deps.profile_store = spy
    topic = client.post("/api/topics", json={"name": "CV off"}).json()["id"]
    cv = spy.register_cv("Synthetic.pdf", b"orig", "CANONICAL-CV-TEXT-12345", {"status": "ready"})
    spy.select_cv(cv["id"], expected_revision=1)
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 200
    assert "read_extracted_text" not in spy.cv_reads


def test_cv_on_includes_canonical_cv_text_in_admitted_plan(tmp_path):
    client = _client(tmp_path)
    app = client.app
    topic = client.post("/api/topics", json={"name": "CV on"}).json()["id"]
    conversation = "default"
    cv = app.state.deps.profile_store.register_cv(
        "Synthetic.pdf",
        b"orig",
        "CANONICAL-CV-TEXT-998877",
        {"status": "ready"},
    )
    app.state.deps.profile_store.select_cv(cv["id"], expected_revision=1)
    client.patch(
        f"/api/topics/{topic}/conversations/{conversation}/learner-context",
        json={"expected_revision": 0, "include_cv": True},
    )

    class _RecordingModel(FakeModel):
        def __init__(self):
            super().__init__()
            self.last_messages: list[dict] | None = None

        async def stream_chat(self, messages, *args, **kwargs):
            self.last_messages = messages
            async for event in FakeModel.stream_chat(self, messages, *args, **kwargs):
                yield event

    recording = _RecordingModel()
    app.state.deps.model_backend = recording
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 200
    assert recording.last_messages is not None
    contents = [message["content"] for message in recording.last_messages if message["role"] == "user"]
    assert any("CANONICAL-CV-TEXT-998877" in content for content in contents)


def test_does_not_fit_refusal_saves_no_user(tmp_path, monkeypatch):
    # admission_only: build_chat_prompt runs inside admission graph before execution
    import lab.workflows.chat as chat_workflow

    def does_not_fit(*_args, **_kwargs):
        raise DoesNotFit("selected material does not fit")

    monkeypatch.setattr(chat_workflow, "build_chat_prompt", does_not_fit)
    client = _client(tmp_path)
    topic = client.post("/api/topics", json={"name": "Fit"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 422
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["user_saved"] is False


def test_indexed_and_mixed_attachments_admit_user_once(tmp_path):
    client = _client(tmp_path)
    topic = client.post("/api/topics", json={"name": "Mixed"}).json()["id"]
    indexed = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nsynthetic", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    assert indexed["index_status"] == "ready"
    unindexed = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("notes.pdf", b"%PDF-1.7\nattachment body", "application/pdf")},
        data={"parser": "markitdown"},
    ).json()
    assert unindexed.get("index_status") != "ready"
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={**payload(), "file_ids": [indexed["id"], unindexed["id"]]},
    )
    assert response.status_code == 200
    session = client.get(f"/api/topics/{topic}/messages").json()
    user_messages = [message for message in session["messages"] if message["role"] == "user"]
    assert len(user_messages) == 1
    assert set(user_messages[0]["file_ids"]) == {indexed["id"], unindexed["id"]}


def test_admission_graph_callables_are_async_coroutines():
    graphs = build_chat_graphs()
    for name, fn in graph_callables(graphs.admission):
        assert inspect.iscoroutinefunction(fn), f"{name} is not async"


def test_admission_graph_mermaid_contains_expected_nodes():
    graphs = build_chat_graphs()
    mermaid = graphs.admission.get_graph().draw_mermaid()
    for node in (
        "load_session",
        "select_attachments",
        "capture_snapshot",
        "load_context",
        "initial_retrieval",
        "vision_probe",
        "build_prompt",
        "save_user",
    ):
        assert node in mermaid


def test_recursion_limit_constant_matches_longest_path():
    assert ADMISSION_RECURSION_LIMIT >= 9


@pytest.mark.anyio
async def test_graph_run_cancelled_before_start_does_not_start_new_task():
    from langgraph.graph import END, START, StateGraph

    class S(dict):
        pass

    async def wait_forever(_state, runtime):
        del runtime
        await asyncio.Event().wait()
        return {}

    builder = StateGraph(S)
    builder.add_node("wait", wait_forever)
    builder.add_edge(START, "wait")
    builder.add_edge("wait", END)
    compiled = builder.compile()
    sink = EventSink(allowed_types=frozenset({"token"}))
    run = GraphRun(
        graph=compiled,
        state={},
        context=object(),
        recursion_limit=5,
        sink=sink,
    )
    await run.cancel_and_wait()
    with pytest.raises(asyncio.CancelledError):
        await run.result()
    events = [item async for item in run.events()]
    assert events == []


def test_older_summary_import_still_loads_during_admission(tmp_path):
    from tests.test_summary_imports_api import _body, _client as summary_fixture_client, _import_path

    client, _, topic, outline, section_id, summary, _model = summary_fixture_client(tmp_path)
    client.app.state.deps.model_backend = FakeModel()
    imported = client.post(_import_path(topic), json=_body(outline, section_id, summary))
    assert imported.status_code == 200
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 200
    session = client.get(f"/api/topics/{topic}/messages").json()
    assert any("summary_import" in message for message in session["messages"])
