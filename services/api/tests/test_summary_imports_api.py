from __future__ import annotations

import json
import asyncio

from docling_core.types.doc import DoclingDocument
from fastapi.testclient import TestClient
import pytest

from lab.chat_session import history_messages
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


def test_named_conversation_import_and_history_projection_keep_metadata_out_of_model_context(tmp_path):
    client, store, topic, outline, section_id, summary, _ = _client(tmp_path)
    named = store.create_conversation(topic, "Reading notes")
    response = client.post(_import_path(topic, named["id"]), json=_body(outline, section_id, summary))

    assert response.status_code == 200
    default = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    named_session = client.get(f"/api/topics/{topic}/conversations/{named['id']}/messages").json()
    assert default == []
    assert named_session["messages"][0]["summary_import"]["summary_id"] == summary["id"]
    projected = history_messages(named_session)
    assert projected == [{"role": "user", "content": named_session["messages"][0]["content"]}]
    assert "summary_import" not in projected[0]


def test_stale_revision_and_incomplete_or_unknown_summary_are_refused(tmp_path):
    client, store, topic, outline, section_id, summary, _ = _client(tmp_path)
    (store.topic(topic) / "paper.pdf").write_bytes(b"%PDF-1.7 changed")
    stale = client.post(_import_path(topic), json=_body(outline, section_id, summary))
    assert stale.status_code == 409

    rebuilt = client.post(f"/api/topics/{topic}/files/paper-1/map").json()["map"]
    body = {**_body(rebuilt, rebuilt["sections"][0]["id"], summary), "revision": rebuilt["revision"]}
    assert client.post(_import_path(topic), json=body).status_code == 404


def test_new_summary_revision_imports_as_distinct_snapshot(tmp_path):
    client, store, topic, outline, section_id, old_summary, model = _client(tmp_path)
    path = _import_path(topic)
    assert client.post(path, json=_body(outline, section_id, old_summary)).status_code == 200

    (store.topic(topic) / "paper.pdf").write_bytes(b"%PDF-1.7 new revision")
    updated_outline = client.post(f"/api/topics/{topic}/files/paper-1/map").json()["map"]
    updated_section_id = updated_outline["sections"][0]["id"]
    new_response = client.post(
        f"/api/topics/{topic}/files/paper-1/map/sections/{updated_section_id}/summary",
        json={"revision": updated_outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )
    new_summary = json.loads(new_response.text.splitlines()[-1])["summary"]
    result = client.post(path, json=_body(updated_outline, updated_section_id, new_summary))

    assert result.status_code == 200
    assert result.json()["imported"] is True
    assert len(result.json()["messages"]) == 2
    assert (
        result.json()["messages"][0]["summary_import"]["revision"]
        != result.json()["messages"][1]["summary_import"]["revision"]
    )
    assert len(model.summary_requests) == 2


def test_concurrent_exact_imports_commit_one_snapshot(tmp_path):
    import lab.web.summary_imports as summary_import_routes
    from lab.web.schemas import SummaryImportInput

    client, _, topic, outline, section_id, summary, _ = _client(tmp_path)
    deps = client.app.state.deps
    endpoint = summary_import_routes.router(deps).routes[0].endpoint
    body = SummaryImportInput(**_body(outline, section_id, summary))

    async def concurrent_imports():
        return await asyncio.gather(endpoint(topic, "default", body), endpoint(topic, "default", body))

    first, second = asyncio.run(concurrent_imports())

    assert sorted([first["imported"], second["imported"]]) == [False, True]
    session = client.get(f"/api/topics/{topic}/messages").json()
    assert len(session["messages"]) == 1


def test_malformed_saved_import_metadata_fails_on_session_read(tmp_path):
    client, store, topic, outline, section_id, summary, _ = _client(tmp_path)
    response = client.post(_import_path(topic), json=_body(outline, section_id, summary))
    assert response.status_code == 200
    session = store.session(topic)
    session["messages"][0]["summary_import"]["sources"][0]["pages"] = [-1]
    store.save_session(topic, session)

    assert client.get(f"/api/topics/{topic}/messages").status_code == 500


@pytest.mark.parametrize(
    "mutation",
    [
        "negative_page",
        "duplicate_label",
        "duplicate_unit",
        "naive_timestamp",
        "reversed_timestamp",
        "empty_body",
        "unknown_label",
    ],
)
def test_malformed_immutable_snapshot_is_rejected_on_read(tmp_path, mutation):
    client, store, topic, outline, section_id, summary, _ = _client(tmp_path)
    response = client.post(_import_path(topic), json=_body(outline, section_id, summary))
    assert response.status_code == 200
    session = store.session(topic)
    message = session["messages"][0]
    metadata = message["summary_import"]
    if mutation == "negative_page":
        metadata["sources"][0]["pages"] = [-1, 0]
    elif mutation == "duplicate_label":
        metadata["sources"] = [metadata["sources"][0], {**metadata["sources"][0], "unit_id": "other-unit"}]
    elif mutation == "duplicate_unit":
        metadata["sources"] = [metadata["sources"][0], {**metadata["sources"][0], "label": "S2"}]
    elif mutation == "naive_timestamp":
        metadata["imported_at"] = "2026-10-05T12:00:00"
    elif mutation == "reversed_timestamp":
        metadata["imported_at"] = "2020-01-01T00:00:00+00:00"
    elif mutation == "empty_body":
        message["content"] = (
            f"Saved section summary — {metadata['section_title']}\nGenerated summary, not verbatim PDF text.\n\n"
        )
    else:
        message["content"] += " Fabricated claim [S999]."
    store.save_session(topic, session)

    assert client.get(f"/api/topics/{topic}/messages").status_code == 500


def test_idempotent_retry_must_match_original_section_identity(tmp_path):
    client, _, topic, outline, section_id, summary, _ = _client(tmp_path)
    body = _body(outline, section_id, summary)
    first = client.post(_import_path(topic), json=body)
    assert first.status_code == 200

    retry = client.post(_import_path(topic), json={**body, "section_id": "another-section"})

    assert retry.status_code == 409
