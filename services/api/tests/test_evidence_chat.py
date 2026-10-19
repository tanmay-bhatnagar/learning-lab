"""HTTP lifecycle contract for the optional answer-or-search chat workflow."""

from __future__ import annotations

import asyncio
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
