"""Explicit prerequisite handoff to an existing main conversation."""

from copy import deepcopy

from fastapi.testclient import TestClient

from lab.conversation_profile import get_conversation_profile
from lab.prerequisite_store import write_prerequisite_attempt
from lab.storage import write_json
from lab.web.app import create_app
from tests.test_prerequisite_store import _assessment, _attempt


def _prepared(tmp_path, monkeypatch):
    app = create_app(tmp_path / "Learning", tmp_path / "settings.json", profile_root=tmp_path / "Profile")
    client = TestClient(app)
    store = app.state.deps.store
    topic = store.create("Synthetic prerequisite handoff")["id"]
    write_json(
        store.topic(topic) / "files.json", [{"id": "synthetic-paper", "name": "synthetic.pdf", "status": "ready"}]
    )
    attempt = {
        **_attempt(status="completed", finished_at="2026-10-12T10:01:00+00:00"),
        "topic_id": topic,
        "started_at": "2026-10-12T10:00:00+00:00",
    }
    assessment = {**_assessment(), "topic_id": topic, "finished_at": attempt["finished_at"]}
    write_prerequisite_attempt(
        store, topic, "synthetic-paper", {**attempt, "status": "generating", "finished_at": None}
    )
    write_prerequisite_attempt(store, topic, "synthetic-paper", attempt, assessment=assessment)
    module = __import__("lab.web.prerequisite_imports", fromlist=["router"])
    monkeypatch.setattr(
        module,
        "get_document_map",
        lambda *_args: {
            "status": "ready",
            "map": {
                "revision": "a" * 64,
                "sections": [{"id": "section-1", "title": "Synthetic Methods", "children": []}],
            },
        },
    )
    if not any(
        getattr(route, "path", None).endswith("/prerequisite-imports")
        for route in app.routes
        if getattr(route, "path", None)
    ):
        app.include_router(module.router(app.state.deps))
    return app, client, topic


def _payload(**updates):
    return {
        "file_id": "synthetic-paper",
        "assessment_id": "assessment-1",
        "revision": "a" * 64,
        "section_id": "section-1",
        "expected_revision": 0,
        **updates,
    }


def test_handoff_uses_captured_existing_destination_idempotently_without_inference(tmp_path, monkeypatch):
    app, client, topic = _prepared(tmp_path, monkeypatch)
    dest = app.state.deps.store.create_conversation(topic, "Main chat")["id"]
    old_default = deepcopy(app.state.deps.store.session(topic))
    url = f"/api/topics/{topic}/conversations/{dest}/prerequisite-imports"
    first = client.post(url, json=_payload())
    assert first.status_code == 200
    assert first.json()["imported"] is True
    assert first.json()["conversation_id"] == dest
    assert len(first.json()["messages"]) == 1
    assert "model-inferred" in first.json()["message"]["content"]
    prefs = get_conversation_profile(app.state.deps.store, topic, dest)
    assert prefs["include_cv"] is False
    assert prefs["active_assessment"]["assessment_id"] == "assessment-1"
    assert prefs["active_assessment"]["goal"] == "Understand synthetic section"
    second = client.post(url, json=_payload(expected_revision=prefs["revision"]))
    assert second.status_code == 200 and second.json()["imported"] is False
    assert second.json()["messages"] == first.json()["messages"]
    assert app.state.deps.store.session(topic) == old_default
    assert (
        client.post(f"/api/topics/{topic}/conversations/unknown/prerequisite-imports", json=_payload()).status_code
        == 404
    )


def test_stale_or_invalid_handoff_has_no_message_or_focus_write(tmp_path, monkeypatch):
    app, client, topic = _prepared(tmp_path, monkeypatch)
    url = f"/api/topics/{topic}/conversations/default/prerequisite-imports"
    before = deepcopy(app.state.deps.store.session(topic))
    for updates in [{"revision": "b" * 64}, {"assessment_id": "missing"}, {"expected_revision": 2}]:
        response = client.post(url, json=_payload(**updates))
        assert response.status_code in {404, 409}
        assert app.state.deps.store.session(topic) == before
        assert get_conversation_profile(app.state.deps.store, topic)["active_assessment"] is None


def test_focus_save_failure_can_retry_without_duplicate_snapshot(tmp_path, monkeypatch):
    app, client, topic = _prepared(tmp_path, monkeypatch)
    module = __import__("lab.web.prerequisite_imports", fromlist=["save_conversation_profile"])
    original = module.save_conversation_profile

    def fail(*_args, **_kwargs):
        raise OSError("Synthetic preference publication failure")

    monkeypatch.setattr(module, "save_conversation_profile", fail)
    url = f"/api/topics/{topic}/conversations/default/prerequisite-imports"
    with TestClient(app, raise_server_exceptions=False) as safeclient:
        assert safeclient.post(url, json=_payload()).status_code == 500
    assert len(app.state.deps.store.session(topic)["messages"]) == 1
    assert get_conversation_profile(app.state.deps.store, topic)["active_assessment"] is None
    monkeypatch.setattr(module, "save_conversation_profile", original)
    retry = client.post(url, json=_payload())
    assert retry.status_code == 200 and retry.json()["imported"] is False
    assert len(retry.json()["messages"]) == 1
    assert get_conversation_profile(app.state.deps.store, topic)["active_assessment"]["assessment_id"] == "assessment-1"
