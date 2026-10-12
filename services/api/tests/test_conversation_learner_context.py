"""HTTP and chat contracts for conversation-local learner context."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lab.web.app import create_app
from tests.fakes import FakeModel


def _app(tmp_path, model=None):
    return create_app(
        tmp_path / "Learning",
        tmp_path / "state" / "settings.json",
        model_backend=model or FakeModel(),
        profile_root=tmp_path / "profile",
    )


def _learner_context_url(topic: str, conversation: str = "default") -> str:
    return f"/api/topics/{topic}/conversations/{conversation}/learner-context"


def test_preferences_are_versioned_and_cv_inclusion_is_explicit(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    topic = client.post("/api/topics", json={"name": "Synthetic learner context"}).json()["id"]
    conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "Named conversation"}).json()["id"]
    cv = app.state.deps.profile_store.register_cv(
        "Synthetic CV.pdf", b"synthetic original", "Complete synthetic CV text.", {"status": "ready"}
    )
    app.state.deps.profile_store.select_cv(cv["id"], expected_revision=1)

    default = client.get(_learner_context_url(topic))
    named = client.get(_learner_context_url(topic, conversation))

    assert default.status_code == 200
    assert default.json() == {
        "schema_version": 1,
        "revision": 0,
        "include_cv": False,
        "active_assessment": None,
    }
    assert named.json() == default.json()

    saved = client.patch(_learner_context_url(topic, conversation), json={"expected_revision": 0, "include_cv": True})

    assert saved.status_code == 200
    assert saved.json() == {**default.json(), "revision": 1, "include_cv": True}
    assert client.get(_learner_context_url(topic)).json() == default.json()


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_revision": True, "include_cv": False},
        {"expected_revision": 0, "include_cv": 1},
        {"expected_revision": 0, "include_cv": False, "active_assessment": {}},
        {"expected_revision": 0},
    ],
)
def test_preference_patch_rejects_coercion_and_server_owned_focus(tmp_path, payload):
    client = TestClient(_app(tmp_path))
    topic = client.post("/api/topics", json={"name": "Synthetic strict contract"}).json()["id"]

    response = client.patch(_learner_context_url(topic), json=payload)

    assert response.status_code == 422
    assert client.get(_learner_context_url(topic)).json()["revision"] == 0


def test_enable_requires_eligible_cv_but_disabling_remains_available_after_revoke(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    topic = client.post("/api/topics", json={"name": "Synthetic CV eligibility"}).json()["id"]
    url = _learner_context_url(topic)

    assert client.patch(url, json={"expected_revision": 0, "include_cv": True}).status_code == 409
    cv = app.state.deps.profile_store.register_cv(
        "Synthetic CV.pdf", b"synthetic original", "Complete synthetic CV text.", {"status": "ready"}
    )
    app.state.deps.profile_store.select_cv(cv["id"], expected_revision=1)
    assert client.patch(url, json={"expected_revision": 0, "include_cv": True}).status_code == 200

    app.state.deps.profile_store.revoke_cv(cv["id"], expected_revision=2)
    disabled = client.patch(url, json={"expected_revision": 1, "include_cv": False})

    assert disabled.status_code == 200
    assert disabled.json()["include_cv"] is False


def test_manual_proficiency_is_reloaded_for_each_default_and_named_chat(tmp_path):
    model = FakeModel()
    app = _app(tmp_path, model)
    client = TestClient(app)
    topic = client.post("/api/topics", json={"name": "Synthetic chat context"}).json()["id"]
    conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "Second context"}).json()["id"]
    state = app.state.deps.profile_store.add_proficiency(
        concept="Synthetic algebra",
        comfort="comfortable",
        notes="Can solve small examples",
        expected_revision=0,
    )

    for conversation_id in ("default", conversation):
        path = (
            f"/api/topics/{topic}/chat"
            if conversation_id == "default"
            else f"/api/topics/{topic}/conversations/{conversation_id}/chat"
        )
        response = client.post(path, json={"message": "How should I begin?", "file_ids": [], "model": "fake"})
        events = [json.loads(line) for line in response.text.splitlines() if line]

        assert response.status_code == 200
        assert events[-1]["type"] == "done"
        assert "Synthetic algebra" in json.dumps(model.calls[-1])
        assert "comfortable" in json.dumps(model.calls[-1])

    app.state.deps.profile_store.update_proficiency(
        state["entries"][0]["id"],
        updates={"comfort": "refresher"},
        expected_revision=state["revision"],
    )
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "I changed my confidence", "file_ids": [], "model": "fake"},
    )

    assert response.status_code == 200
    assert "refresher" in json.dumps(model.calls[-1])
