from __future__ import annotations

import json

from docling_core.types.doc import DoclingDocument
from fastapi.testclient import TestClient

from lab.storage import Store, write_json
from lab.web.app import create_app
from tests.test_document_map_summaries_api import SummaryFakeModel


def _client(tmp_path):
    root = tmp_path / "Learning"
    policy_path = tmp_path / "runtime-policy.md"
    policy_path.write_text("Synthetic runtime policy.", encoding="utf-8")
    model = SummaryFakeModel()
    app = create_app(root, tmp_path / "state" / "settings.json", model_backend=model, runtime_policy_path=policy_path)
    client = TestClient(app)
    store: Store = app.state.deps.store
    topic = store.create("Synthetic import test")["id"]
    doc = DoclingDocument(name="Synthetic source")
    section = doc.add_heading("Results", level=1)
    doc.add_text(label="text", text="The synthetic result is 42.", parent=section)
    (store.topic(topic) / "paper.pdf").write_bytes(b"%PDF-1.7 synthetic")
    write_json(store.file_path(topic, "paper.docling.json"), doc.export_to_dict())
    write_json(
        store.topic(topic) / "files.json",
        [
            {
                "id": "paper-1",
                "name": "paper.pdf",
                "original_name": "paper.pdf",
                "docling_name": "paper.docling.json",
                "parser": "docling",
                "status": "ready",
            }
        ],
    )
    outline = client.post(f"/api/topics/{topic}/files/paper-1/map").json()["map"]
    section_id = outline["sections"][0]["id"]
    generated = client.post(
        f"/api/topics/{topic}/files/paper-1/map/sections/{section_id}/summary",
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )
    summary_event = json.loads(generated.text.splitlines()[-1])
    return client, store, topic, outline, section_id, summary_event["summary"], model


def _import_path(topic: str, conversation_id: str = "default") -> str:
    return f"/api/topics/{topic}/conversations/{conversation_id}/summary-imports"


def _body(outline, section_id, summary):
    return {
        "file_id": "paper-1",
        "revision": outline["revision"],
        "section_id": section_id,
        "summary_id": summary["id"],
    }


def test_import_appends_server_owned_snapshot_to_existing_conversation(tmp_path):
    client, _, topic, outline, section_id, summary, model = _client(tmp_path)

    response = client.post(_import_path(topic), json=_body(outline, section_id, summary))

    assert response.status_code == 200
    result = response.json()
    assert result["imported"] is True
    message = result["message"]
    assert message["role"] == "user"
    assert summary["content"] in message["content"]
    assert message["summary_import"]["summary_id"] == summary["id"]
    assert message["summary_import"]["sources"] == summary["sources"]
    assert model.summary_requests  # Generation happened before import; import itself makes no further call.
    assert len(model.summary_requests) == 1


def test_import_retry_after_map_rebuild_returns_original_snapshot_once(tmp_path):
    client, store, topic, outline, section_id, summary, _ = _client(tmp_path)
    path = _import_path(topic)
    body = _body(outline, section_id, summary)
    first = client.post(path, json=body)
    assert first.status_code == 200

    (store.topic(topic) / "paper.pdf").write_bytes(b"%PDF-1.7 newer synthetic source")
    rebuilt = client.post(f"/api/topics/{topic}/files/paper-1/map")
    assert rebuilt.status_code == 200
    retry = client.post(path, json=body)

    assert retry.status_code == 200
    assert retry.json()["imported"] is False
    assert retry.json()["message"] == first.json()["message"]
    session = client.get(f"/api/topics/{topic}/conversations/default/messages").json()
    assert len(session["messages"]) == 1


def test_import_refuses_client_text_and_unknown_conversation(tmp_path):
    client, _, topic, outline, section_id, summary, _ = _client(tmp_path)
    malicious = {**_body(outline, section_id, summary), "content": "forged summary"}
    assert client.post(_import_path(topic), json=malicious).status_code == 422
    assert (
        client.post(_import_path(topic, "missing-conversation"), json=_body(outline, section_id, summary)).status_code
        == 404
    )
