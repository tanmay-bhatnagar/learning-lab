from __future__ import annotations

import json

import pytest
from docling_core.types.doc import DoclingDocument
from fastapi.testclient import TestClient

from lab.storage import Store, write_json, write_text
from lab.web.app import create_app
from tests.fakes import FakeModel


def _client(tmp_path):
    root = tmp_path / "Learning"
    app = create_app(root, tmp_path / "state" / "settings.json", model_backend=FakeModel())
    client = TestClient(app)
    store: Store = app.state.deps.store
    topic = store.create("Map")['id']
    other_topic = store.create("Other")['id']
    file_id = "paper-1"
    original_name = "paper.pdf"
    docling_name = "paper.docling.json"
    document = DoclingDocument(name="synthetic research paper")
    document.add_heading("Methods", level=1)
    document.add_text(label="text", text="A synthetic method.")
    (store.topic(topic) / original_name).write_bytes(b"%PDF-1.7 synthetic")
    write_json(store.file_path(topic, docling_name), document.export_to_dict())
    write_json(
        store.topic(topic) / "files.json",
        [
            {
                "id": file_id,
                "name": "paper.pdf",
                "original_name": original_name,
                "docling_name": docling_name,
                "parser": "docling",
                "status": "ready",
            }
        ],
    )
    return client, store, topic, other_topic, file_id


def test_map_get_is_on_demand_and_build_returns_section_source_metadata(tmp_path):
    client, store, topic, _, file_id = _client(tmp_path)
    base = f"/api/topics/{topic}/files/{file_id}/map"

    before = client.get(base)
    assert before.status_code == 200
    assert before.json() == {"status": "not_built", "map": None}
    assert not store.file_path(topic, f"{file_id}.map.json").exists()

    built = client.post(base)
    assert built.status_code == 200
    assert built.json()["status"] == "ready"
    outline = built.json()["map"]
    assert outline["outline_mode"] == "headings"
    assert outline["sections"][0]["title"] == "Methods"
    section = client.get(f"{base}/sections/{outline['sections'][0]['id']}")
    assert section.status_code == 200
    assert section.json()["section"]["text"] == "Methods\n\nA synthetic method."
    assert section.json()["section"]["source_unit_ids"] == outline["sections"][0]["source_unit_ids"]
    assert section.json()["section"]["last_summary"] is None


def test_map_is_idempotent_preserves_saved_summary_and_stale_rebuild_keeps_history(tmp_path):
    client, store, topic, _, file_id = _client(tmp_path)
    base = f"/api/topics/{topic}/files/{file_id}/map"
    first = client.post(base).json()["map"]
    first["sections"][0]["last_summary"] = {"text": "Saved section result"}
    write_json(store.file_path(topic, f"{file_id}.map.json"), first)

    same = client.post(base).json()["map"]
    assert same["sections"][0]["last_summary"] == {"text": "Saved section result"}
    (store.topic(topic) / "paper.pdf").write_bytes(b"%PDF-1.7 changed source")
    stale = client.get(base).json()
    assert stale["status"] == "stale"
    assert stale["map"]["revision"] == first["revision"]

    rebuilt = client.post(base).json()["map"]
    assert rebuilt["revision"] != first["revision"]
    assert rebuilt["sections"][0]["last_summary"] is None
    assert rebuilt["history"][0]["sections"][0]["last_summary"] == {"text": "Saved section result"}


def test_map_storage_rejects_corrupt_nested_data_and_unknown_versions(tmp_path):
    client, store, topic, _, file_id = _client(tmp_path)
    base = f"/api/topics/{topic}/files/{file_id}/map"
    record = client.post(base).json()["map"]
    path = store.file_path(topic, f"{file_id}.map.json")

    malformed = json.loads(json.dumps(record))
    malformed["sections"][0]["children"] = "not-a-list"
    write_json(path, malformed)
    assert client.get(base).status_code == 500

    unknown = json.loads(json.dumps(record))
    unknown["schema_version"] = 999
    write_json(path, unknown)
    assert client.get(base).status_code == 500


@pytest.mark.parametrize("parser,status", [("markitdown", "ready"), ("docling", "processing")])
def test_map_requires_a_ready_docling_file(tmp_path, parser, status):
    client, store, topic, _, file_id = _client(tmp_path)
    records = store.files(topic)
    records[0]["parser"] = parser
    records[0]["status"] = status
    write_json(store.topic(topic) / "files.json", records)

    response = client.post(f"/api/topics/{topic}/files/{file_id}/map")
    assert response.status_code == 409


def test_map_file_and_paths_remain_topic_scoped(tmp_path):
    client, _, topic, other_topic, file_id = _client(tmp_path)

    assert client.post(f"/api/topics/{other_topic}/files/{file_id}/map").status_code == 404
    assert client.get(f"/api/topics/{topic}/files/../map").status_code in {400, 404}


def test_failed_atomic_map_write_does_not_replace_existing_record(tmp_path, monkeypatch):
    import lab.document_map_store as map_store

    client, store, topic, _, file_id = _client(tmp_path)
    base = f"/api/topics/{topic}/files/{file_id}/map"
    assert client.post(base).status_code == 200
    path = store.file_path(topic, f"{file_id}.map.json")
    before = path.read_bytes()

    def fail_write(*_args, **_kwargs):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(map_store, "write_json", fail_write)
    response = client.post(base)

    assert response.status_code == 500
    assert path.read_bytes() == before
