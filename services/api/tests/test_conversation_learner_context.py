"""HTTP and chat contracts for conversation-local learner context."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lab.storage import write_json
from lab.web.app import create_app
from lab.web.conversation_profile import router as learner_context_router
from lab.web.prerequisite_imports import router as prerequisite_import_router
from tests.fakes import FakeModel


def _app(tmp_path, model=None):
    app = create_app(
        tmp_path / "Learning",
        tmp_path / "state" / "settings.json",
        model_backend=model or FakeModel(),
        profile_root=tmp_path / "profile",
    )
    if not any(
        getattr(route, "path", None) == "/api/topics/{topic}/conversations/{conversation_id}/learner-context"
        for route in app.routes
    ):
        app.include_router(learner_context_router(app.state.deps))
    return app


def _learner_context_url(topic: str, conversation: str = "default") -> str:
    return f"/api/topics/{topic}/conversations/{conversation}/learner-context"


def _focused_context_chat(tmp_path):
    from tests.test_web_prerequisites import _events, _prepared, _request

    client, topic, outline, model, _cv = _prepared(tmp_path)
    app = client.app
    conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "Focused learner context"}).json()[
        "id"
    ]
    for route_path, route_factory in (
        (
            "/api/topics/{topic}/conversations/{conversation_id}/learner-context",
            learner_context_router,
        ),
        (
            "/api/topics/{topic}/conversations/{conversation_id}/prerequisite-imports",
            prerequisite_import_router,
        ),
    ):
        if not any(getattr(route, "path", None) == route_path for route in app.routes):
            app.include_router(route_factory(app.state.deps))
    if not any(getattr(route, "path", None) == "/api/topics/{topic}/chat" for route in app.routes):
        from lab.web.chat import router as chat_router

        app.include_router(chat_router(app.state.deps))
    section = outline["sections"][0]
    generated = client.post(
        f"/api/topics/{topic}/files/paper-1/map/sections/{section['id']}/prerequisites",
        json=_request(outline),
    )
    assessment = _events(generated)[-1]["assessment"]
    imported = client.post(
        f"/api/topics/{topic}/conversations/{conversation}/prerequisite-imports",
        json={
            "file_id": "paper-1",
            "assessment_id": assessment["assessment_id"],
            "revision": outline["revision"],
            "section_id": section["id"],
            "expected_revision": 0,
        },
    )
    assert imported.status_code == 200
    return client, app, topic, conversation, assessment, model


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
    stale = client.patch(_learner_context_url(topic, conversation), json={"expected_revision": 0, "include_cv": False})
    assert stale.status_code == 409
    assert client.get(_learner_context_url(topic, conversation)).json() == saved.json()


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_revision": True, "include_cv": False},
        {"expected_revision": -1, "include_cv": False},
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


def test_complete_cv_text_is_added_once_to_every_request_only_when_enabled(tmp_path):
    model = FakeModel()
    app = _app(tmp_path, model)
    client = TestClient(app)
    topic = client.post("/api/topics", json={"name": "Synthetic full CV context"}).json()["id"]
    cv = app.state.deps.profile_store.register_cv(
        "First CV.pdf",
        b"first synthetic original",
        "FIRST-CV-LITERAL-SENTINEL full canonical text",
        {"status": "ready"},
    )
    app.state.deps.profile_store.select_cv(cv["id"], expected_revision=1)
    url = _learner_context_url(topic)

    disabled = client.post(
        f"/api/topics/{topic}/chat", json={"message": "First question", "file_ids": [], "model": "fake"}
    )
    assert disabled.status_code == 200
    assert "FIRST-CV-LITERAL-SENTINEL" not in json.dumps(model.calls[-1])
    assert client.patch(url, json={"expected_revision": 0, "include_cv": True}).status_code == 200

    first = client.post(
        f"/api/topics/{topic}/chat", json={"message": "Second question", "file_ids": [], "model": "fake"}
    )
    assert first.status_code == 200
    assert json.dumps(model.calls[-1]).count("FIRST-CV-LITERAL-SENTINEL full canonical text") == 1

    replacement = app.state.deps.profile_store.register_cv(
        "Replacement CV.pdf",
        b"replacement synthetic original",
        "REPLACEMENT-CV-LITERAL-SENTINEL latest full text",
        {"status": "ready"},
    )
    profile = app.state.deps.profile_store.read_profile()
    app.state.deps.profile_store.select_cv(replacement["id"], expected_revision=profile["revision"])
    latest = client.post(
        f"/api/topics/{topic}/chat", json={"message": "Third question", "file_ids": [], "model": "fake"}
    )

    assert latest.status_code == 200
    assert json.dumps(model.calls[-1]).count("REPLACEMENT-CV-LITERAL-SENTINEL latest full text") == 1
    assert "FIRST-CV-LITERAL-SENTINEL" not in json.dumps(model.calls[-1])


def test_cv_off_chat_does_not_read_or_block_on_corrupt_cv_text(tmp_path):
    model = FakeModel()
    app = _app(tmp_path, model)
    client = TestClient(app)
    topic = client.post("/api/topics", json={"name": "Synthetic CV opt out"}).json()["id"]
    cv = app.state.deps.profile_store.register_cv(
        "Corruptible CV.pdf", b"synthetic original", "Integrity protected text", {"status": "ready"}
    )
    text_path = app.state.deps.profile_store._text_path(cv["id"])
    text_path.write_text("tampered after registration", encoding="utf-8")

    response = client.post(
        f"/api/topics/{topic}/chat", json={"message": "Chat without CV", "file_ids": [], "model": "fake"}
    )

    assert response.status_code == 200
    assert "Integrity protected text" not in json.dumps(model.calls[-1])


def test_protected_cv_budget_failure_happens_before_user_turn_is_saved(tmp_path):
    model = FakeModel()
    app = _app(tmp_path, model)
    client = TestClient(app)
    topic = client.post("/api/topics", json={"name": "Synthetic oversized CV"}).json()["id"]
    cv = app.state.deps.profile_store.register_cv(
        "Large CV.pdf", b"synthetic original", "UNIQUE-CV-TEXT " + ("career detail " * 12000), {"status": "ready"}
    )
    app.state.deps.profile_store.select_cv(cv["id"], expected_revision=1)
    assert (
        client.patch(_learner_context_url(topic), json={"expected_revision": 0, "include_cv": True}).status_code == 200
    )
    before = client.get(f"/api/topics/{topic}/messages").content

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "This must not persist", "file_ids": [], "model": "fake", "context_limit": 1024},
    )

    assert response.status_code == 422
    assert client.get(f"/api/topics/{topic}/messages").content == before
    assert model.calls == []


def test_chat_uses_only_selected_historical_assessment_and_latest_answers_after_cv_revoke(tmp_path):
    from tests.test_web_prerequisites import _events, _prepared, _request

    client, topic, outline, model, cv = _prepared(tmp_path)
    app = client.app
    conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "Focused learning"}).json()["id"]
    if not any(
        getattr(route, "path", None) == "/api/topics/{topic}/conversations/{conversation_id}/learner-context"
        for route in app.routes
    ):
        app.include_router(learner_context_router(app.state.deps))
    if not any(
        getattr(route, "path", None) == "/api/topics/{topic}/conversations/{conversation_id}/prerequisite-imports"
        for route in app.routes
    ):
        app.include_router(prerequisite_import_router(app.state.deps))
    if not any(getattr(route, "path", None) == "/api/topics/{topic}/chat" for route in app.routes):
        from lab.web.chat import router as chat_router

        app.include_router(chat_router(app.state.deps))
    section = outline["sections"][0]
    generated = client.post(
        f"/api/topics/{topic}/files/paper-1/map/sections/{section['id']}/prerequisites",
        json=_request(outline),
    )
    first_assessment = _events(generated)[-1]["assessment"]
    model.output = json.dumps(
        {
            "overview": "SECOND-ONLY assessment overview.",
            "requirements": [
                {
                    "concept": "SECOND-ONLY concept",
                    "reason": "This belongs to a different completed assessment.",
                    "source_labels": ["S1"],
                    "cv_background": "not_stated",
                    "cv_source_labels": [],
                    "cv_quote": "",
                }
            ],
        }
    )
    second = client.post(
        f"/api/topics/{topic}/files/paper-1/map/sections/{section['id']}/prerequisites",
        json=_request(outline),
    )
    second_assessment = _events(second)[-1]["assessment"]
    assert second_assessment["assessment_id"] != first_assessment["assessment_id"]
    imported = client.post(
        f"/api/topics/{topic}/conversations/{conversation}/prerequisite-imports",
        json={
            "file_id": "paper-1",
            "assessment_id": first_assessment["assessment_id"],
            "revision": outline["revision"],
            "section_id": section["id"],
            "expected_revision": 0,
        },
    )
    assert imported.status_code == 200
    proficiency = app.state.deps.profile_store.read_proficiency()
    first_requirement = next(
        entry for entry in proficiency["entries"] if entry.get("assessment_id") == first_assessment["assessment_id"]
    )
    app.state.deps.profile_store.save_proficiency_batch(
        additions=[],
        updates=[
            {
                "id": first_requirement["id"],
                "comfort": "comfortable",
                "notes": "LATEST-ANSWER-SENTINEL",
            }
        ],
        expected_revision=proficiency["revision"],
    )
    unrelated = app.state.deps.profile_store.read_proficiency()
    unrelated_row = next(
        entry for entry in unrelated["entries"] if entry.get("assessment_id") == second_assessment["assessment_id"]
    )
    unrelated_row["requirement_id"] = "req-" + ("f" * 24)
    unrelated_row["concept"] = "SECOND-ONLY forged assessment concept"
    write_json(app.state.deps.profile_store.proficiency_path, unrelated)
    profile = app.state.deps.profile_store.read_profile()
    app.state.deps.profile_store.revoke_cv(cv["id"], expected_revision=profile["revision"])

    response = client.post(
        f"/api/topics/{topic}/conversations/{conversation}/chat",
        json={"message": "Teach me this", "file_ids": [], "model": "synthetic-model"},
    )

    assert response.status_code == 200
    messages = model.requests[-1]["messages"]
    prompt = json.dumps(messages)
    assert "Understand this section at a high level" in prompt
    assert "This section uses basic algorithms and probability." in prompt
    assert "Basic programming" in prompt
    assert "LATEST-ANSWER-SENTINEL" in prompt
    assert "pending" in prompt
    assert "SECOND-ONLY" not in prompt
    assert "Synthetic CV evidence." not in prompt


@pytest.mark.parametrize(
    "damage",
    ["unknown_requirement", "changed_concept", "missing_requirement", "duplicate_requirement"],
)
def test_corrupt_selected_assessment_proficiency_links_block_chat_before_save(tmp_path, damage):
    client, app, topic, conversation, assessment, model = _focused_context_chat(tmp_path)
    profile = app.state.deps.profile_store.read_proficiency()
    selected = [entry for entry in profile["entries"] if entry.get("assessment_id") == assessment["assessment_id"]]
    assert len(selected) == len(assessment["requirements"])
    first = selected[0]
    if damage == "unknown_requirement":
        first["requirement_id"] = "req-" + ("e" * 24)
    elif damage == "changed_concept":
        first["concept"] = "Forged concept with a valid requirement ID"
    elif damage == "missing_requirement":
        profile["entries"] = [entry for entry in profile["entries"] if entry["id"] != first["id"]]
    else:
        profile["entries"].append({**first, "id": "d" * 32})
    write_json(app.state.deps.profile_store.proficiency_path, profile)
    before = client.get(f"/api/topics/{topic}/conversations/{conversation}/messages").content
    calls_before = len(model.requests)

    response = client.post(
        f"/api/topics/{topic}/conversations/{conversation}/chat",
        json={"message": "Do not use corrupt familiarity", "file_ids": [], "model": "synthetic-model"},
    )

    assert response.status_code == 500
    assert "proficiency" in response.json()["detail"].lower() or "requirement" in response.json()["detail"].lower()
    assert client.get(f"/api/topics/{topic}/conversations/{conversation}/messages").content == before
    assert len(model.requests) == calls_before
