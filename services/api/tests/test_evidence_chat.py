"""HTTP lifecycle contract for the optional answer-or-search chat workflow."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from lab.web.app import create_app
from tests.test_retrieval_api import fake_structured_parser


class EvidenceModel:
    def __init__(self, actions: list[str] | None = None):
        self.actions = list(actions or [])
        self.calls: list[dict[str, object]] = []

    async def list_models(self):
        return {"models": [{"id": "local", "vision": False}]}

    async def embed_texts(self, texts, model, *, generation_lock):
        async with generation_lock:
            return [[0.1] for _ in texts]

    def stream_chat(
        self,
        messages,
        model,
        think=None,
        context_limit=8192,
        context_metadata=None,
        *,
        generation_lock,
        response_schema=None,
    ):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "think": think,
                "context_limit": context_limit,
                "response_schema": response_schema,
            }
        )
        action = self.actions.pop(0) if response_schema else None

        async def stream():
            async with generation_lock:
                if action is not None:
                    yield {"type": "thinking", "text": "private planner"}
                    yield {"type": "token", "text": action}
                else:
                    yield {"type": "token", "text": "Grounded answer."}
                yield {
                    "type": "done",
                    "model": model,
                    "context": {"used": 77, "limit": context_limit, "estimated": False},
                }

        return stream()


def _structured_parser(*args, **kwargs):
    metadata, chunks = fake_structured_parser(*args, **kwargs)
    for chunk in chunks:
        chunk["content_hash"] = hashlib.sha256(str(chunk["text"]).encode()).hexdigest()
    artifact_path = args[0].file_path(args[1], metadata["chunks_name"])
    stored = [json.loads(line) for line in artifact_path.read_text(encoding="utf-8").splitlines() if line]
    for row, chunk in zip(stored, chunks, strict=True):
        row["content_hash"] = chunk["content_hash"]
    serialized = "\n".join(json.dumps(row, ensure_ascii=False) for row in stored) + "\n"
    artifact_path.write_text(serialized, encoding="utf-8")
    return metadata, chunks


def _app(tmp_path, model=None):
    return create_app(
        tmp_path / "Learning",
        tmp_path / "settings.json",
        model_backend=model or EvidenceModel(),
        structured_parser=_structured_parser,
    )


def _chat_scope(topic: str, body: bytes, spec_version: str) -> dict[str, object]:
    path = f"/api/topics/{topic}/chat"
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


def _topic_with_index(client: TestClient):
    topic = client.post("/api/topics", json={"name": "Evidence chat"}).json()["id"]
    uploaded = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nsynthetic evidence", "application/pdf")},
        data={"parser": "docling"},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["index_status"] == "ready"
    return topic, uploaded.json()


def _retriever(calls):
    async def retrieve(store, topic, query, *, file_ids, limit, embedding_model, embedder):
        calls.append((query, tuple(file_ids)))
        records = [store.file(topic, file_id) for file_id in file_ids]
        record = records[0]
        return {
            "hits": [
                {
                    "chunk_id": f"{record['id']}:text:000000",
                    "file_id": record["id"],
                    "file_name": record["name"],
                    "chunk_index": 0,
                    "text": "Calibration\nThe calibration value is exactly 42.",
                    "headings": ["Calibration"],
                    "pages": [1],
                    "bboxes": [],
                    "asset_ids": [],
                    "content_hash": hashlib.sha256(
                        "Calibration\nThe calibration value is exactly 42.".encode()
                    ).hexdigest(),
                    "trace": {},
                }
            ],
            "mode": "keyword",
        }

    return retrieve


def _search_retriever(calls):
    async def retrieve(store, topic, query, *, file_ids, limit, embedding_model, embedder):
        calls.append((query, tuple(file_ids)))
        file_id = sorted(file_ids)[min(len(calls) - 1, 1)]
        from lab.index import TopicIndex

        with TopicIndex(store.file_path(topic, "retrieval.sqlite")) as index:
            chunk = index.get_chunks(file_ids=[file_id])[0]
        chunk["trace"] = {}
        return {
            "hits": [chunk],
            "mode": "hybrid",
        }

    return retrieve


def test_chat_input_exposes_a_strict_opt_in_flag():
    from lab.web.schemas import ChatInput

    assert ChatInput(message="Question", model="local").extra_search is False
    assert ChatInput(message="Question", model="local", extra_search=True).extra_search is True
    with pytest.raises(ValueError):
        ChatInput(message="Question", model="local", extra_search="yes")


def test_opt_in_requires_an_indexed_selection_before_saving_user_message(tmp_path):
    client = TestClient(_app(tmp_path))
    topic = client.post("/api/topics", json={"name": "No source"}).json()["id"]

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "Explain", "file_ids": [], "model": "local", "extra_search": True},
    )

    assert response.status_code == 400
    assert client.get(f"/api/topics/{topic}/messages").json()["messages"] == []


def test_opted_in_direct_answer_streams_safe_status_and_persists_metadata(tmp_path):
    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "The value is 42.", "source_labels": ["E1"], "query": ""})]
    )
    calls = []
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever(calls)
    client = TestClient(app)
    topic, record = _topic_with_index(client)

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "What value?",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.status_code == 200
    assert [event.get("stage") for event in events if event.get("type") == "evidence_status"] == [
        "deciding",
        "answering",
    ]
    assert [call["response_schema"] is not None for call in model.calls] == [True]
    assert all(event.get("text") != "private planner" for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["context"]["used"] == 77
    assert events[-1]["retrieval"]["evidence_search"]["outcome"] == "direct_answer"
    saved = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert saved[-1]["retrieval"]["evidence_search"]["declared_source_labels"] == ["E1"]
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["evidence_search"]["outcome"] == "direct_answer"
    assert calls == [("What value?", (record["id"],))]
    assert trace["status"] == "completed"


def test_opted_out_chat_keeps_legacy_single_generation_without_status(tmp_path):
    model = EvidenceModel()
    client = TestClient(_app(tmp_path, model))
    topic = client.post("/api/topics", json={"name": "Legacy"}).json()["id"]

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "Question", "file_ids": [], "model": "local"},
    )

    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.status_code == 200
    assert len(model.calls) == 1
    assert model.calls[0]["response_schema"] is None
    assert all(event["type"] != "evidence_status" for event in events)
    assert "evidence_search" not in events[-1]["retrieval"]


def test_search_action_uses_only_captured_selection_and_saves_actual_evidence(tmp_path):
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
    calls = []
    app = _app(tmp_path, model)
    app.state.deps.retriever = _search_retriever(calls)
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
            "message": "What value was validated?",
            "file_ids": [record["id"], second["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    events = [json.loads(line) for line in response.text.splitlines()]
    done = events[-1]
    metadata = done["retrieval"]["evidence_search"]
    assert response.status_code == 200
    assert [event["stage"] for event in events if event["type"] == "evidence_status"] == [
        "deciding",
        "searching",
        "answering",
    ]
    assert [call["response_schema"] is not None for call in model.calls] == [True, False]
    assert calls == [
        ("What value was validated?", selected_ids),
        ("validation value", selected_ids),
    ]
    assert done["type"] == "done"
    assert metadata["outcome"] == "searched"
    assert metadata["lookup_count"] == 1
    assert metadata["new_chunk_ids"] == [f"{selected_ids[1]}:text:000000"]
    assert metadata["retained_new_chunk_ids"] == [f"{selected_ids[1]}:text:000000"]
    assert set(metadata["final_chunk_ids"]) == {f"{file_id}:text:000000" for file_id in selected_ids}
    assert {citation["chunk_id"] for citation in done["retrieval"]["citations"]} == set(metadata["final_chunk_ids"])
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["evidence_search"] == metadata
    assert {chunk["chunk_id"] for chunk in trace["retained_chunks"]} == set(metadata["final_chunk_ids"])


def test_invalid_structured_action_falls_back_to_one_ordinary_answer(tmp_path):
    model = EvidenceModel(["not valid structured output"])
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Explain the value.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    events = [json.loads(line) for line in response.text.splitlines()]
    done = events[-1]
    assert response.status_code == 200
    assert len(model.calls) == 2
    assert [event["stage"] for event in events if event["type"] == "evidence_status"] == [
        "deciding",
        "answering",
    ]
    assert done["type"] == "done"
    assert done["retrieval"]["evidence_search"]["outcome"] == "invalid_action_fallback"
    assert done["retrieval"]["evidence_search"]["warning"]


def test_named_conversation_supports_the_same_explicit_opt_in(tmp_path):
    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Grounded in E1.", "source_labels": ["E1"], "query": ""})]
    )
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "Evidence"}).json()["id"]

    response = client.post(
        f"/api/topics/{topic}/conversations/{conversation}/chat",
        json={
            "message": "What does E1 say?",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    done = [json.loads(line) for line in response.text.splitlines()][-1]
    assert response.status_code == 200
    assert done["retrieval"]["evidence_search"]["outcome"] == "direct_answer"
    saved = client.get(f"/api/topics/{topic}/conversations/{conversation}/messages").json()["messages"]
    assert saved[-1]["retrieval"] == done["retrieval"]


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
def test_disconnect_before_iteration_does_not_claim_prepared_evidence(tmp_path, spec_version):
    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Grounded.", "source_labels": ["E1"], "query": ""})]
    )
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    body = json.dumps(
        {
            "message": "Explain this source.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        }
    ).encode()
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            raise OSError("client disconnected before reading stream")

    try:
        asyncio.run(app(_chat_scope(topic, body, spec_version), receive, send))
    except OSError:
        pass

    assert model.calls == []
    saved = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assistant = saved[-1]
    metadata = assistant["retrieval"]["evidence_search"]
    assert assistant.get("incomplete") is True
    assert assistant["retrieval"]["citations"] == []
    assert metadata["initial_chunk_ids"] == []
    assert metadata["final_chunk_ids"] == []
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["retained_chunks"] == []
    assert trace["evidence_search"]["final_chunk_ids"] == []


@pytest.mark.parametrize(
    ("stage", "action", "expected_calls", "expected_generation_count", "expected_lookup_count"),
    [
        ("deciding", "search_selected", 0, 0, 0),
        ("searching", "search_selected", 1, 1, 1),
        ("answering", "search_selected", 2, 2, 1),
    ],
)
def test_disconnect_at_each_workflow_stage_saves_cancelled_metadata(
    tmp_path, stage, action, expected_calls, expected_generation_count, expected_lookup_count
):
    model = EvidenceModel([json.dumps({"action": action, "answer": "", "source_labels": [], "query": "more evidence"})])
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    body = json.dumps(
        {
            "message": "Explain this source.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        }
    ).encode()
    received = False
    observed_stages = []

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Future()

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            for raw_line in message["body"].splitlines():
                event = json.loads(raw_line)
                if event.get("type") == "evidence_status":
                    observed_stages.append(event["stage"])
                    if event["stage"] == stage:
                        raise OSError("client stopped at workflow stage")

    app.user_middleware = [item for item in app.user_middleware if item.cls.__name__ != "BaseHTTPMiddleware"]
    app.middleware_stack = None
    try:
        asyncio.run(app(_chat_scope(topic, body, "2.3"), receive, send))
    except OSError:
        pass

    assert stage in observed_stages
    assert len(model.calls) == expected_calls
    saved = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert saved[-1].get("incomplete") is True
    metadata = saved[-1]["retrieval"]["evidence_search"]
    assert metadata["outcome"] == "cancelled"
    assert metadata["generation_count"] == expected_generation_count
    assert metadata["lookup_count"] == expected_lookup_count
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["status"] == "cancelled"
    assert trace["stage"] == stage
    assert not app.state.deps.locks[topic].locked()


def test_initial_gateway_factory_failure_does_not_claim_prepared_evidence(tmp_path):
    class FailingFactory(EvidenceModel):
        def stream_chat(
            self,
            messages,
            model,
            think=None,
            context_limit=8192,
            context_metadata=None,
            *,
            generation_lock,
            response_schema=None,
        ):
            self.calls.append({"messages": messages, "response_schema": response_schema})
            raise RuntimeError("private provider detail")

    model = FailingFactory()
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Explain this source.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    events = [json.loads(line) for line in response.text.splitlines()]
    saved = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assistant = saved[-1]
    metadata = assistant["retrieval"]["evidence_search"]
    assert response.status_code == 200
    assert events[-1]["type"] == "error"
    assert "private provider detail" not in response.text
    assert assistant.get("incomplete") is True
    assert assistant["retrieval"]["citations"] == []
    assert metadata["initial_chunk_ids"] == []
    assert metadata["final_chunk_ids"] == []
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["retained_chunks"] == []
    assert trace["evidence_search"]["final_chunk_ids"] == []


def test_snapshot_conflict_remains_specific_in_saved_trace(tmp_path, monkeypatch):
    from lab.errors import Conflict

    def stale_snapshot(*args, **kwargs):
        raise Conflict("Captured prompt inputs changed.")

    monkeypatch.setattr("lab.web.chat.revalidate_evidence_snapshot", stale_snapshot)
    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Grounded.", "source_labels": ["E1"], "query": ""})]
    )
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Explain this source.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert response.status_code == 200
    assert [json.loads(line) for line in response.text.splitlines()][-1]["type"] == "error"
    assert model.calls == []
    assert trace["status"] == "error"
    assert trace["error"]["code"] == "snapshot_changed"


def test_captured_cv_goal_and_proficiency_are_present_in_both_model_prompts(tmp_path):
    model = EvidenceModel(
        [
            json.dumps(
                {
                    "action": "search_selected",
                    "answer": "",
                    "source_labels": [],
                    "query": "calibration",
                }
            )
        ]
    )
    app = _app(tmp_path, model)
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    goal = "Compare the calibration evidence before learning more statistics."
    assert client.put(f"/api/topics/{topic}/learning-goal", json={"learning_goal": goal}).status_code == 200
    cv = app.state.deps.profile_store.register_cv(
        "Synthetic CV.pdf", b"synthetic CV original", "PINNED-CV-TEXT education and work", {"status": "ready"}
    )
    app.state.deps.profile_store.select_cv(cv["id"], expected_revision=1)
    assert (
        client.patch(
            f"/api/topics/{topic}/conversations/default/learner-context",
            json={"expected_revision": 0, "include_cv": True},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/profile/proficiency/entries",
            json={
                "expected_revision": 0,
                "concept": "Statistics",
                "comfort": "refresher",
                "notes": "Review confidence intervals.",
            },
        ).status_code
        == 201
    )
    app.state.deps.retriever = _retriever([])

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "What does this evidence support?",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    assert response.status_code == 200
    assert len(model.calls) == 2
    for call in model.calls:
        prompt = json.dumps(call["messages"], ensure_ascii=False)
        assert goal in prompt
        assert "PINNED-CV-TEXT education and work" in prompt
        assert "Statistics" in prompt
        assert "confidence intervals" in prompt


def test_opted_in_cv_off_does_not_read_corrupt_cv_text(tmp_path):
    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Evidence-only answer.", "source_labels": ["E1"], "query": ""})]
    )
    app = _app(tmp_path, model)
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    cv = app.state.deps.profile_store.register_cv(
        "Opt-out CV.pdf", b"synthetic CV original", "DO-NOT-READ-CV-TEXT", {"status": "ready"}
    )
    app.state.deps.profile_store.select_cv(cv["id"], expected_revision=1)
    app.state.deps.profile_store._text_path(cv["id"]).write_text("tampered CV text", encoding="utf-8")
    app.state.deps.retriever = _retriever([])

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Answer from the selected document.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    assert response.status_code == 200
    assert len(model.calls) == 1
    assert "DO-NOT-READ-CV-TEXT" not in json.dumps(model.calls, ensure_ascii=False)


def test_followup_image_uses_selected_model_vision_even_when_initial_search_is_empty(tmp_path):
    class VisionModel(EvidenceModel):
        def __init__(self):
            super().__init__(
                [json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "figure"})]
            )
            self.model_list_calls = 0

        async def list_models(self):
            self.model_list_calls += 1
            return {"models": [{"id": "local", "vision": True}]}

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00"
        b"\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    model = VisionModel()
    app = _app(tmp_path, model)
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    asset_path = app.state.deps.store.file_path(topic, "figure.png")
    asset_path.write_bytes(png)
    from lab.index import TopicIndex

    with TopicIndex(app.state.deps.store.file_path(topic, "retrieval.sqlite")) as index:
        indexed = index.get_chunks(file_ids=[record["id"]])
        indexed[0]["asset_ids"] = ["figure.png"]
        index.replace_file(record["id"], indexed)
    retrieve_calls = 0

    async def empty_then_image(store, selected_topic, query, *, file_ids, limit, embedding_model, embedder):
        nonlocal retrieve_calls
        retrieve_calls += 1
        if retrieve_calls == 1:
            return {"hits": [], "mode": "none"}
        with TopicIndex(store.file_path(selected_topic, "retrieval.sqlite")) as index:
            chunk = index.get_chunks(file_ids=file_ids)[0]
        return {"hits": [chunk], "mode": "hybrid"}

    app.state.deps.retriever = empty_then_image
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Explain the figure.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    assert response.status_code == 200
    assert retrieve_calls == 2
    assert model.model_list_calls == 1
    final_messages = model.calls[-1]["messages"]
    assert any(message.get("images") == [base64.b64encode(png).decode("ascii")] for message in final_messages)
