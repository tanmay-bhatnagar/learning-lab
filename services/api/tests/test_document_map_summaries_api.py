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
    def __init__(self, output: str = "A synthetic statement [S1].", behavior: str = "done"):
        super().__init__()
        self.output = output
        self.behavior = behavior
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
                if self.behavior == "error":
                    yield {"type": "error", "message": "synthetic provider failure"}
                    return
                if self.behavior == "eof":
                    return
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
    assert not client.app.state.deps.locks[topic].locked()
    assert client.app.state.deps.active_document_map_summaries == {}


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


def test_failed_regeneration_preserves_previous_durable_summary(tmp_path):
    model = SummaryFakeModel()
    client, _, topic, outline, _ = _client(tmp_path, model=model)
    section = outline["sections"][0]
    url = _summary_url(topic, outline["revision"], section["id"])
    request = {"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None}
    first = _events(client.post(url, json=request))
    assert first[-1]["type"] == "done"
    model.output = "New result with no source label."

    failed = _events(client.post(url, json=request))
    assert failed[-1]["type"] == "error"
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"]["status"] == "error"
    assert saved["last_summary"]["content"] == "A synthetic statement [S1]."


def test_provider_error_and_premature_eof_are_terminal_failures(tmp_path):
    for behavior in ("error", "eof"):
        model = SummaryFakeModel(behavior=behavior)
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


def test_terminal_write_failure_never_emits_done_and_releases_topic(tmp_path, monkeypatch):
    import lab.web.document_map_summaries as summary_routes
    from lab.errors import CorruptData

    client, _, topic, outline, model = _client(tmp_path)
    section = outline["sections"][0]
    write_attempt = summary_routes.write_summary_attempt

    def fail_summary_write(store, write_topic, file_id, attempt, *, summary=None):
        if summary is not None:
            raise CorruptData("synthetic durable write failure")
        return write_attempt(store, write_topic, file_id, attempt)

    monkeypatch.setattr(summary_routes, "write_summary_attempt", fail_summary_write)
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )

    events = _events(response)
    assert events[-1]["type"] == "error"
    assert all(event["type"] != "done" for event in events)
    state = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert state["latest_attempt"]["status"] == "error"
    assert state["last_summary"] is None
    assert not client.app.state.deps.locks[topic].locked()
    assert client.app.state.deps.active_document_map_summaries == {}
    assert len(model.summary_requests) == 1


def test_map_read_recovers_abandoned_generating_attempt(tmp_path):
    from lab.document_map_summary_store import write_summary_attempt
    from lab.section_summary import build_section_summary_plan

    client, store, topic, outline, _ = _client(tmp_path)
    section = outline["sections"][0]
    plan = build_section_summary_plan(
        outline,
        section["id"],
        runtime_policy="Synthetic full runtime policy.",
        model="fake",
        context_limit=8192,
        think=None,
        attempt_id="abandoned-attempt",
        started_at="2026-10-05T00:00:00+00:00",
    )
    write_summary_attempt(store, topic, "paper-1", plan["attempt"])

    recovered = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert recovered["latest_attempt"]["status"] == "interrupted"
    assert recovered["latest_attempt"]["error"] == "Generation ended before completion. Retry the summary."
