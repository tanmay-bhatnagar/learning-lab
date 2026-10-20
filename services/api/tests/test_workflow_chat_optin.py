"""Gates 8–10: opt-in (extra_search) chat execution graph and publication."""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest
from fastapi.testclient import TestClient

from lab.workflows.chat import build_chat_graphs
from lab.workflows.chat_evidence import OPTIN_EXECUTION_RECURSION_LIMIT, optin_execution_graph_callables
from lab.workflows.chat_publication import ChatPublicationOutcome, emit_late_graph_failure
from lab.workflows.events import EventSink
from lab.workflows.runtime import GraphRun
from tests.test_evidence_chat import EvidenceModel, _app, _retriever, _search_retriever, _topic_with_index
from tests.test_query_traces import payload
from tests.test_workflow_characterization import _DecisionStreamModel


def _events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_optin_execution_graph_callables_are_async():
    graphs = build_chat_graphs()
    for name, fn in optin_execution_graph_callables(graphs.optin_execution):
        assert inspect.iscoroutinefunction(fn), name


def test_optin_mermaid_contains_decision_lookup_and_publish():
    mermaid = build_chat_graphs().optin_execution.get_graph().draw_mermaid()
    assert "decision" in mermaid
    assert "lookup" in mermaid
    assert "merge_final_plan" in mermaid
    assert "stream_final_answer" in mermaid
    assert "prepare_publication" in mermaid
    assert "direct_answer" in mermaid
    assert "invalid_prepare" in mermaid


def test_optin_recursion_limit_constant():
    assert OPTIN_EXECUTION_RECURSION_LIMIT >= 12


def test_extra_search_direct_answer_via_graph(tmp_path):
    answer_text = "Direct from graph."
    model = EvidenceModel(
        [
            json.dumps(
                {
                    "action": "answer",
                    "answer": answer_text,
                    "source_labels": ["E1"],
                    "query": "",
                }
            )
        ]
    )
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            **payload(message="What value?"),
            "file_ids": [record["id"]],
            "extra_search": True,
        },
    )
    events = _events(response)
    assert [event["type"] for event in events] == ["evidence_status", "evidence_status", "token", "done"]
    tokens = "".join(event.get("text", "") for event in events if event.get("type") == "token")
    assert tokens == answer_text
    assert events[-1]["retrieval"]["evidence_search"]["outcome"] == "direct_answer"


def test_extra_search_invalid_action_fallback_via_graph(tmp_path):
    model = EvidenceModel(["not valid structured output"])
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            **payload(message="Explain."),
            "file_ids": [record["id"]],
            "extra_search": True,
        },
    )
    events = _events(response)
    assert events[-1]["type"] == "done"
    metadata = events[-1]["retrieval"]["evidence_search"]
    assert metadata["outcome"] == "invalid_action_fallback"
    assert metadata["generation_count"] == 2
    assert len(model.calls) == 2


def _slow_search_retriever(calls: list[tuple[str, tuple[str, ...]]], *, sleep_on_query: str):
    inner = _search_retriever(calls)

    async def retrieve(store, topic, query, *, file_ids, limit, embedding_model, embedder):
        if query == sleep_on_query:
            await asyncio.sleep(0.2)
        return await inner(
            store, topic, query, file_ids=file_ids, limit=limit, embedding_model=embedding_model, embedder=embedder
        )

    return retrieve


def test_extra_search_lookup_elapsed_ms_in_saved_trace(tmp_path):
    lookup_query = "validation value"
    model = EvidenceModel(
        [
            json.dumps(
                {
                    "action": "search_selected",
                    "answer": "",
                    "source_labels": [],
                    "query": lookup_query,
                }
            )
        ]
    )
    retrieval_calls: list[tuple[str, tuple[str, ...]]] = []
    app = _app(tmp_path, model)
    app.state.deps.retriever = _slow_search_retriever(retrieval_calls, sleep_on_query=lookup_query)
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    second = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("second.pdf", b"%PDF-1.7\nsecond synthetic evidence", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    selected_ids = tuple(sorted((record["id"], second["id"])))
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            **payload(message="What value was validated?"),
            "file_ids": list(selected_ids),
            "extra_search": True,
        },
    )
    assert response.status_code == 200
    events = _events(response)
    assert events[-1]["type"] == "done"
    assert events[-1]["retrieval"]["evidence_search"]["outcome"] == "searched"
    assert retrieval_calls[-1][0] == lookup_query
    from lab.query_traces import list_traces, trace_path

    trace = list_traces(trace_path(client.app.state.deps.store.topic(topic)), conversation_id="default", limit=1)[0]
    assert trace["retrieval_ms"] >= 200

    direct_model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Direct.", "source_labels": ["E1"], "query": ""})]
    )
    direct_calls: list[tuple[str, tuple[str, ...]]] = []
    app_direct = _app(tmp_path, direct_model)
    app_direct.state.deps.retriever = _slow_search_retriever(direct_calls, sleep_on_query=lookup_query)
    client_direct = TestClient(app_direct)
    topic_direct, record_direct = _topic_with_index(client_direct)
    client_direct.post(
        f"/api/topics/{topic_direct}/chat",
        json={
            **payload(message="What value was validated?"),
            "file_ids": [record_direct["id"]],
            "extra_search": True,
        },
    )
    trace_direct = list_traces(
        trace_path(client_direct.app.state.deps.store.topic(topic_direct)), conversation_id="default", limit=1
    )[0]
    assert trace_direct["retrieval_ms"] < 200


def test_extra_search_lookup_path_two_generations_one_lookup(tmp_path):
    model = EvidenceModel(
        [
            json.dumps(
                {
                    "action": "search_selected",
                    "answer": "",
                    "source_labels": [],
                    "query": "validation value",
                }
            )
        ]
    )
    retrieval_calls: list[tuple[str, tuple[str, ...]]] = []
    app = _app(tmp_path, model)
    app.state.deps.retriever = _search_retriever(retrieval_calls)
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    second = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("second.pdf", b"%PDF-1.7\nsecond synthetic evidence", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    selected_ids = tuple(sorted((record["id"], second["id"])))
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            **payload(message="What value was validated?"),
            "file_ids": list(selected_ids),
            "extra_search": True,
        },
    )
    events = _events(response)
    assert [event["type"] for event in events] == [
        "evidence_status",
        "evidence_status",
        "evidence_status",
        "token",
        "done",
    ]
    assert len(model.calls) == 2
    metadata = events[-1]["retrieval"]["evidence_search"]
    assert metadata["outcome"] == "searched"
    assert metadata["generation_count"] == 2
    assert metadata["lookup_count"] == 1
    assert retrieval_calls == [
        ("What value was validated?", selected_ids),
        ("validation value", selected_ids),
    ]


def test_extra_search_decision_provider_error_traces_provider_failed(tmp_path):
    model = _DecisionStreamModel("provider_error")
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            **payload(message="Explain this source."),
            "file_ids": [record["id"]],
            "extra_search": True,
        },
    )
    events = _events(response)
    assert events[-1]["type"] == "error"
    assert len(model.calls) == 1
    from lab.query_traces import list_traces, trace_path

    trace = list_traces(trace_path(client.app.state.deps.store.topic(topic)), conversation_id="default", limit=1)[0]
    assert trace["status"] == "error"
    assert trace["error"]["code"] == "provider_failed"


def test_named_conversation_extra_search_route(tmp_path):
    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Named opt-in.", "source_labels": ["E1"], "query": ""})]
    )
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "Evidence thread"}).json()["id"]
    response = client.post(
        f"/api/topics/{topic}/conversations/{conversation}/chat",
        json={
            **payload(message="Question?"),
            "file_ids": [record["id"]],
            "extra_search": True,
        },
    )
    assert response.status_code == 200
    assert _events(response)[-1]["type"] == "done"


def test_save_before_trace_on_optin_success(tmp_path):
    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Saved first.", "source_labels": ["E1"], "query": ""})]
    )
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    client.post(
        f"/api/topics/{topic}/chat",
        json={**payload(), "file_ids": [record["id"]], "extra_search": True},
    )
    from lab.query_traces import list_traces, trace_path

    trace = list_traces(trace_path(client.app.state.deps.store.topic(topic)), conversation_id="default", limit=1)[0]
    assert trace["assistant_saved"] is True
    assert trace["status"] == "completed"


def test_trace_finalize_failure_preserves_optin_answer(tmp_path, monkeypatch):
    import lab.query_traces as query_traces_module

    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Grounded.", "source_labels": ["E1"], "query": ""})]
    )

    def fail_finalize(*_args, **_kwargs):
        raise RuntimeError("trace store down")

    monkeypatch.setattr(query_traces_module, "finalize", fail_finalize)
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={**payload(), "file_ids": [record["id"]], "extra_search": True},
    )
    events = _events(response)
    assert events[-1]["type"] == "error"
    assert "trace could not be finalized" in events[-1]["message"]
    assert not any(event.get("type") == "done" for event in events)
    messages = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1].get("incomplete") is not True


@pytest.mark.anyio
async def test_late_graph_failure_after_optin_publication_emits_error_without_duplicate_save():
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
async def test_slow_consumer_bounds_optin_producer():
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


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
@pytest.mark.parametrize("http_middleware", [True, False])
@pytest.mark.parametrize(
    ("scenario", "model_factory"),
    [
        (
            "direct",
            lambda: EvidenceModel(
                [json.dumps({"action": "answer", "answer": "Grounded.", "source_labels": ["E1"], "query": ""})]
            ),
        ),
        (
            "fallback",
            lambda: EvidenceModel(["not valid structured output"]),
        ),
        (
            "search",
            lambda: EvidenceModel(
                [
                    json.dumps(
                        {
                            "action": "search_selected",
                            "answer": "",
                            "source_labels": [],
                            "query": "validation value",
                        }
                    )
                ]
            ),
        ),
    ],
)
def test_disconnect_on_final_token_saves_cancelled_incomplete_optin(
    tmp_path, spec_version, http_middleware, scenario, model_factory
):
    from tests.test_evidence_chat import _chat_scope

    model = model_factory()
    app = _app(tmp_path, model)
    retrieval_calls: list[tuple[str, tuple[str, ...]]] = []
    if scenario == "search":
        app.state.deps.retriever = _search_retriever(retrieval_calls)
    else:
        app.state.deps.retriever = _retriever([])
    if not http_middleware:
        app.user_middleware = [item for item in app.user_middleware if item.cls.__name__ != "BaseHTTPMiddleware"]
        app.middleware_stack = None
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    file_ids = [record["id"]]
    if scenario == "search":
        second = client.post(
            f"/api/topics/{topic}/files",
            files={"file": ("second.pdf", b"%PDF-1.7\nsecond synthetic evidence", "application/pdf")},
            data={"parser": "docling"},
        ).json()
        file_ids = list(sorted((record["id"], second["id"])))
    body = json.dumps(
        {
            **payload(message="What value was validated?" if scenario == "search" else "Explain this source."),
            "file_ids": file_ids,
            "extra_search": True,
        }
    ).encode()
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Future()

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            for raw_line in message["body"].splitlines():
                if json.loads(raw_line).get("type") == "token":
                    raise OSError("client stopped on final token")

    from starlette.requests import ClientDisconnect

    try:
        asyncio.run(app(_chat_scope(topic, body, spec_version), receive, send))
    except (OSError, ClientDisconnect):
        pass

    saved = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert saved[-1]["role"] == "assistant"
    assert saved[-1].get("incomplete") is True
    metadata = saved[-1]["retrieval"]["evidence_search"]
    assert metadata["outcome"] == "cancelled"
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["status"] == "cancelled"
    assert trace.get("assistant_saved") is True


def test_full_read_optin_direct_completes_trace_and_assistant(tmp_path):
    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Saved first.", "source_labels": ["E1"], "query": ""})]
    )
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={**payload(), "file_ids": [record["id"]], "extra_search": True},
    )
    assert _events(response)[-1]["type"] == "done"
    messages = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert messages[-1].get("incomplete") is not True
    from lab.query_traces import list_traces, trace_path

    trace = list_traces(trace_path(client.app.state.deps.store.topic(topic)), conversation_id="default", limit=1)[0]
    assert trace["status"] == "completed"
    assert trace.get("assistant_saved") is True
