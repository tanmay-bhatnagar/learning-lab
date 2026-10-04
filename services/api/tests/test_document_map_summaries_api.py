from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from docling_core.types.doc import DoclingDocument
from fastapi.testclient import TestClient

from lab.storage import Store, write_json
from lab.web.app import create_app
from tests.fakes import FakeModel


class SummaryFakeModel(FakeModel):
    def __init__(self, output: str = "A synthetic statement [S1]."):
        super().__init__()
        self.output = output
        self.summary_requests: list[dict[str, object]] = []

    def stream_chat(
        self,
        messages: list[dict],
        model: str,
        think: bool | str | None,
        context_limit: int,
        context_metadata: dict | None = None,
        *,
        generation_lock: asyncio.Lock,
    ) -> AsyncIterator[dict]:
        self.summary_requests.append(
            {
                "messages": messages,
                "model": model,
                "think": think,
                "context_limit": context_limit,
                "context_metadata": context_metadata,
                "generation_lock": generation_lock,
            }
        )

        async def events() -> AsyncIterator[dict]:
            async with generation_lock:
                yield {"type": "thinking", "text": "checking sources"}
                yield {"type": "token", "text": self.output}
                yield {
                    "type": "done",
                    "context": {"used": 500, "limit": context_limit, "estimated": False},
                    "model": model,
                }

        return events()


def _client(tmp_path, *, model: SummaryFakeModel | None = None, policy: str = "Synthetic full runtime policy."):
    root = tmp_path / "Learning"
    policy_path = tmp_path / "runtime-policy.md"
    policy_path.write_text(policy, encoding="utf-8")
    backend = model or SummaryFakeModel()
    app = create_app(
        root,
        tmp_path / "state" / "settings.json",
        model_backend=backend,
        runtime_policy_path=policy_path,
    )
    client = TestClient(app)
    store: Store = app.state.deps.store
    topic = store.create("Synthetic summary test")['id']
    topic_path = store.topic(topic)
    write_json(topic_path / "topic.json", {"id": topic, "name": "Synthetic", "learning_goal": "PRIVATE GOAL SENTINEL"})
    document = DoclingDocument(name="Synthetic summary paper")
    heading = document.add_heading("Methods", level=1)
    document.add_text(label="text", text="Synthetic method source text.", parent=heading)
    (topic_path / "paper.pdf").write_bytes(b"%PDF-1.7 synthetic only")
    write_json(topic_path / "paper.docling.json", document.export_to_dict())
    write_json(
        topic_path / "files.json",
        [
            {
                "id": "paper-1",
                "name": "Synthetic paper.pdf",
                "original_name": "paper.pdf",
                "docling_name": "paper.docling.json",
                "parser": "docling",
                "status": "ready",
            }
        ],
    )
    store.save_session(topic, {"messages": [{"role": "user", "content": "PRIVATE HISTORY SENTINEL"}]})
    outline = client.post(f"/api/topics/{topic}/files/paper-1/map").json()["map"]
    return client, store, topic, outline, backend


def _summary_url(topic: str, revision: str, section_id: str) -> str:
    return f"/api/topics/{topic}/files/paper-1/map/sections/{section_id}/summary"


def _events(response) -> list[dict[str, object]]:
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_summary_stream_uses_fresh_policy_and_complete_source_without_chat_context(tmp_path):
    client, store, topic, outline, model = _client(tmp_path)
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": False},
    )

    assert response.status_code == 200
    events = _events(response)
    assert [event["type"] for event in events] == ["started", "thinking", "token", "done"]
    assert events[0]["attempt"]["status"] == "generating"
    assert events[-1]["summary"]["content"] == "A synthetic statement [S1]."
    request = model.summary_requests[0]
    messages = request["messages"]
    assert len(messages) == 2
    assert "Synthetic full runtime policy." in messages[0]["content"]
    assert "PRIVATE HISTORY SENTINEL" not in json.dumps(messages)
    assert "PRIVATE GOAL SENTINEL" not in json.dumps(messages)
    assert "Synthetic method source text." in messages[1]["content"]
    assert request["context_metadata"]["truncated_messages"] == 0
    assert request["generation_lock"] is client.app.state.deps.model_generation_lock
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"]["status"] == "completed"
    assert saved["last_summary"]["content"] == "A synthetic statement [S1]."
    assert store.file_path(topic, "paper-1.map.json").exists()


def test_oversized_full_policy_refuses_without_model_call_or_attempt(tmp_path):
    client, _, topic, outline, model = _client(tmp_path, policy="synthetic policy " * 2000)
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 1024, "think": None},
    )

    assert response.status_code == 422
    assert model.summary_requests == []
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"] is None


def test_malformed_source_markers_fail_without_publishing_summary(tmp_path):
    model = SummaryFakeModel("Supported [S1], fabricated [S0].")
    client, _, topic, outline, _ = _client(tmp_path, model=model)
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )

    events = _events(response)
    assert events[-1]["type"] == "error"
    assert events[-1]["attempt"]["status"] == "error"
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"]["status"] == "error"
    assert saved["last_summary"] is None

