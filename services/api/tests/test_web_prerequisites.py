"""HTTP lifecycle tests for on-demand section prerequisite generation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator

from docling_core.types.doc import DoclingDocument
from fastapi.testclient import TestClient
import pytest

from lab.storage import Store, write_json
from lab.web.app import create_app
from lab.web.prerequisites import PrerequisiteInput, router as prerequisite_router


def _model_response() -> str:
    return json.dumps(
        {
            "overview": "This section uses basic algorithms and probability.",
            "requirements": [
                {
                    "concept": "Basic programming",
                    "reason": "The section describes an algorithm.",
                    "source_labels": ["S1"],
                    "cv_background": "not_stated",
                    "cv_source_labels": [],
                    "cv_quote": "",
                },
                {
                    "concept": "Probability",
                    "reason": "The section interprets likelihoods.",
                    "source_labels": ["S1"],
                    "cv_background": "not_stated",
                    "cv_source_labels": [],
                    "cv_quote": "",
                },
            ],
        }
    )


class PrerequisiteFakeModel:
    def __init__(self, *, behavior: str = "done", output: str | None = None, on_done=None):
        self.behavior = behavior
        self.output = output if output is not None else _model_response()
        self.on_done = on_done
        self.requests: list[dict[str, object]] = []
        self.hold_after_token = False
        self.token_sent = asyncio.Event()
        self.allow_done = asyncio.Event()
        self.stream_closed = False

    async def list_models(self) -> dict[str, object]:
        return {"models": [{"id": "synthetic-model"}]}

    async def embed_texts(self, texts, model, *, generation_lock):
        return [[0.0] for _text in texts]

    def stream_chat(
        self,
        messages: list[dict],
        model: str,
        think: bool | str | None,
        context_limit: int,
        context_metadata: dict | None = None,
        *,
        generation_lock: asyncio.Lock,
        response_schema: dict | None = None,
    ) -> AsyncIterator[dict]:
        self.requests.append(
            {
                "messages": messages,
                "model": model,
                "think": think,
                "context_limit": context_limit,
                "context_metadata": context_metadata,
                "generation_lock": generation_lock,
                "response_schema": response_schema,
            }
        )

        async def events() -> AsyncIterator[dict]:
            try:
                async with generation_lock:
                    yield {"type": "thinking", "text": "internal synthetic reasoning"}
                    yield {"type": "token", "text": self.output}
                    self.token_sent.set()
                    if self.hold_after_token:
                        await self.allow_done.wait()
                    if self.behavior == "error":
                        yield {"type": "error", "message": "Synthetic provider failure"}
                        return
                    if self.behavior == "eof":
                        return
                    if self.on_done is not None:
                        self.on_done()
                    yield {"type": "done", "model": model}
            finally:
                self.stream_closed = True

        return events()


def _prepared(
    tmp_path,
    *,
    model: PrerequisiteFakeModel | None = None,
    policy: str = "Synthetic full runtime policy.",
    cv_text: str | None = "Synthetic CV evidence.",
    cv_status: str = "ready",
):
    root = tmp_path / "Learning"
    policy_path = tmp_path / "runtime-policy.md"
    policy_path.write_text(policy, encoding="utf-8")
    gateway = model or PrerequisiteFakeModel()
    app = create_app(
        root,
        tmp_path / "state" / "settings.json",
        model_backend=gateway,
        runtime_policy_path=policy_path,
        profile_root=tmp_path / "profile",
    )
    if not any(
        getattr(route, "path", None) == "/api/topics/{topic}/files/{file_id}/prerequisites" for route in app.routes
    ):
        app.include_router(prerequisite_router(app.state.deps))
    client = TestClient(app)
    store: Store = app.state.deps.store
    topic = store.create("Synthetic prerequisite test")["id"]
    topic_path = store.topic(topic)
    write_json(topic_path / "topic.json", {"id": topic, "name": "Synthetic", "learning_goal": "TOPIC GOAL"})
    document = DoclingDocument(name="Synthetic prerequisite paper")
    heading = document.add_heading("Methods", level=1)
    document.add_text(label="text", text="Synthetic algorithms describe probability.", parent=heading)
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
    store.save_session(topic, {"messages": [{"role": "user", "content": "CHAT HISTORY SENTINEL"}]})
    outline = client.post(f"/api/topics/{topic}/files/paper-1/map").json()["map"]
    cv = None
    if cv_text is not None:
        cv = app.state.deps.profile_store.register_cv(
            "Synthetic CV.pdf",
            b"synthetic original",
            cv_text,
            {"status": cv_status},
        )
        if cv_status == "ready":
            profile = app.state.deps.profile_store.read_profile()
            app.state.deps.profile_store.select_cv(cv["id"], expected_revision=profile["revision"])
    return client, topic, outline, gateway, cv


def _generate_url(topic: str, section_id: str) -> str:
    return f"/api/topics/{topic}/files/paper-1/map/sections/{section_id}/prerequisites"


def _events(response) -> list[dict[str, object]]:
    return [json.loads(line) for line in response.text.splitlines() if line]


def _request(outline, *, revision=None):
    return {
        "revision": revision or outline["revision"],
        "model": "synthetic-model",
        "context_limit": 8192,
        "think": False,
        "goal": "Understand this section at a high level",
    }


def _seed_model_requirement(profile_store, cv, topic, assessment_id, concept="Synthetic pending concept"):
    requirement_id = "req-" + hashlib.sha256(f"{assessment_id}:0".encode()).hexdigest()[:24]
    return profile_store.register_model_requirements(
        [{"requirement_id": requirement_id, "concept": concept}],
        topic_id=topic,
        assessment_id=assessment_id,
        selected_cv_id=cv["id"],
        selected_cv_text_sha256=cv["extracted_sha256"],
    )


def _write_generating_attempt(store, topic, outline, section, cv):
    from lab.prerequisite_store import write_prerequisite_attempt

    attempt_id = "a" * 32
    assessment_id = "b" * 32
    write_prerequisite_attempt(
        store,
        topic,
        "paper-1",
        {
            "id": attempt_id,
            "assessment_id": assessment_id,
            "topic_id": topic,
            "file_id": "paper-1",
            "map_revision": outline["revision"],
            "section_id": section["id"],
            "status": "generating",
            "started_at": "2026-10-13T00:00:00+00:00",
            "finished_at": None,
            "provenance": {
                "prompt_version": "test-v1",
                "source_sha256": "c" * 64,
                "runtime_policy_sha256": "d" * 64,
                "cv_id": cv["id"],
                "cv_text_sha256": cv["extracted_sha256"],
                "goal": "test goal",
                "model": "synthetic-model",
            },
            "diagnostic": None,
        },
    )
    return assessment_id


def test_generation_uses_fresh_full_context_and_only_publishes_on_done(tmp_path):
    client, topic, outline, model, cv = _prepared(tmp_path)
    section = outline["sections"][0]

    response = client.post(_generate_url(topic, section["id"]), json=_request(outline))

    assert response.status_code == 200
    events = _events(response)
    assert [event["type"] for event in events] == ["started", "progress", "done"]
    assert "internal synthetic reasoning" not in response.text
    assert _model_response() not in response.text
    done = events[-1]
    assessment = done["assessment"]
    assert len(assessment["requirements"]) == 2
    assert all(item["comfort"] is None and item["comfort_status"] == "pending" for item in assessment["requirements"])
    assert done["proficiency_revision"] == 1
    call = model.requests[0]
    messages = call["messages"]
    assert len(messages) == 2
    assert messages[0]["content"].count("Synthetic full runtime policy.") == 1
    assert messages[1]["content"].count("Synthetic CV evidence.") == 1
    assert "Synthetic algorithms describe probability." in messages[1]["content"]
    assert "CHAT HISTORY SENTINEL" not in json.dumps(messages)
    assert "TOPIC GOAL" not in json.dumps(messages)
    assert call["response_schema"]["properties"]["requirements"]["items"]["properties"]["source_labels"]["items"][
        "enum"
    ] == [source["label"] for source in assessment["sources"]]
    assert call["generation_lock"] is client.app.state.deps.model_generation_lock


def test_get_returns_versioned_history_current_selection_and_no_cv_text(tmp_path):
    client, topic, outline, _model, cv = _prepared(tmp_path)
    section = outline["sections"][0]
    client.post(_generate_url(topic, section["id"]), json=_request(outline))

    response = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["map_revision"] == outline["revision"]
    assert payload["selected_cv"] == {
        "id": cv["id"],
        "original_name": "Synthetic CV.pdf",
        "extracted_sha256": cv["extracted_sha256"],
    }
    assert payload["current_assessment"]["assessment_id"] == payload["assessments"][-1]["assessment_id"]
    assert "Synthetic CV evidence." not in response.text


def test_historical_assessment_read_survives_corrupt_current_cv_extraction(tmp_path):
    client, topic, outline, _model, cv = _prepared(tmp_path)
    section = outline["sections"][0]
    generated = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))[-1]
    assessment_id = generated["assessment"]["assessment_id"]
    client.app.state.deps.profile_store._text_path(cv["id"]).write_text("tampered current CV", encoding="utf-8")

    historical = client.get(
        f"/api/topics/{topic}/files/paper-1/prerequisites",
        params={"assessment_id": assessment_id},
    )

    assert historical.status_code == 200
    payload = historical.json()
    assert payload["map_revision"] is None
    assert payload["selected_cv"] is None
    assert payload["current_assessment"] is None
    assert next(item for item in payload["assessments"] if item["assessment_id"] == assessment_id) == generated[
        "assessment"
    ]

    current = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites")
    assert current.status_code == 500


def test_historical_assessment_read_returns_exact_record_without_recovery_or_current_inputs(tmp_path, monkeypatch):
    import lab.web.prerequisites as prerequisite_routes

    client, topic, outline, _model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    expected = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))[-1]["assessment"]

    async def reject_recovery(*_args, **_kwargs):
        raise AssertionError("historical reads must not run current-state recovery")

    monkeypatch.setattr(prerequisite_routes, "_recover_if_idle", reject_recovery)
    monkeypatch.setattr(
        prerequisite_routes,
        "get_document_map",
        lambda *_args: (_ for _ in ()).throw(AssertionError("historical reads must not load the current map")),
    )
    monkeypatch.setattr(
        client.app.state.deps.profile_store,
        "read_profile",
        lambda: (_ for _ in ()).throw(AssertionError("historical reads must not load the current CV profile")),
    )

    response = client.get(
        f"/api/topics/{topic}/files/paper-1/prerequisites",
        params={"assessment_id": expected["assessment_id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["map_revision"] is None
    assert payload["selected_cv"] is None
    assert payload["current_assessment"] is None
    assert next(
        item for item in payload["assessments"] if item["assessment_id"] == expected["assessment_id"]
    ) == expected


def test_historical_assessment_read_returns_not_found_for_unknown_id(tmp_path):
    client, topic, _outline, _model, _cv = _prepared(tmp_path)

    response = client.get(
        f"/api/topics/{topic}/files/paper-1/prerequisites",
        params={"assessment_id": "missing-assessment"},
    )

    assert response.status_code == 404


def test_historical_assessment_read_survives_revoking_its_source_cv(tmp_path):
    client, topic, outline, _model, cv = _prepared(tmp_path)
    section = outline["sections"][0]
    expected = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))[-1]["assessment"]
    profile_store = client.app.state.deps.profile_store
    profile = profile_store.read_profile()
    profile_store.revoke_cv(cv["id"], expected_revision=profile["revision"])

    response = client.get(
        f"/api/topics/{topic}/files/paper-1/prerequisites",
        params={"assessment_id": expected["assessment_id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_cv"] is None
    assert payload["current_assessment"] is None
    assert next(
        item for item in payload["assessments"] if item["assessment_id"] == expected["assessment_id"]
    ) == expected


@pytest.mark.parametrize(
    ("kwargs", "request_patch", "expected_status"),
    [
        ({"cv_text": None}, {}, 409),
        ({"cv_text": " ", "cv_status": "error"}, {}, 409),
        ({"policy": "  \n"}, {}, 500),
        ({}, {"revision": "f" * 64}, 409),
        ({"cv_text": "X" * 12000}, {"context_limit": 1024}, 422),
    ],
    ids=["missing-cv", "failed-cv", "missing-policy", "stale-map", "oversized-whole-input"],
)
def test_preflight_failures_never_call_model_or_start_attempt(tmp_path, kwargs, request_patch, expected_status):
    client, topic, outline, model, _cv = _prepared(tmp_path, **kwargs)
    section = outline["sections"][0]
    body = {**_request(outline), **request_patch}

    response = client.post(_generate_url(topic, section["id"]), json=body)

    assert response.status_code == expected_status
    assert model.requests == []
    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites").json()
    assert state["attempts"] == []
    assert state["assessments"] == []


@pytest.mark.parametrize("behavior", ["error", "eof"], ids=["provider-error", "early-eof"])
def test_provider_error_or_early_eof_never_publishes_assessment(tmp_path, behavior):
    model = PrerequisiteFakeModel(behavior=behavior)
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]

    response = client.post(_generate_url(topic, section["id"]), json=_request(outline))

    events = _events(response)
    assert events[-1]["type"] == "error"
    assert events[-1]["attempt"]["status"] == "error"
    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}").json()
    assert state["assessments"] == []
    assert state["current_assessment"] is None
    assert state["attempts"][-1]["status"] == "error"


@pytest.mark.parametrize(
    "output",
    [
        "not-json",
        json.dumps(
            {
                "overview": "Synthetic overview.",
                "requirements": [
                    {
                        "concept": "Programming",
                        "reason": "The section describes an algorithm.",
                        "source_labels": ["S1"],
                        "cv_background": "mentioned",
                        "cv_source_labels": ["CV1"],
                        "cv_quote": "a fact absent from the synthetic CV",
                    }
                ],
            }
        ),
    ],
    ids=["malformed-json", "false-cv-quote"],
)
def test_invalid_model_output_never_becomes_actionable(tmp_path, output):
    model = PrerequisiteFakeModel(output=output)
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]

    response = client.post(_generate_url(topic, section["id"]), json=_request(outline))

    events = _events(response)
    assert events[-1]["type"] == "error"
    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}").json()
    assert state["assessments"] == []
    assert state["current_assessment"] is None
    assert model.requests


def test_cv_change_during_generation_prevents_registration_and_publication(tmp_path):
    model = PrerequisiteFakeModel()
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    profile_store = client.app.state.deps.profile_store
    next_cv = profile_store.register_cv(
        "Next CV.pdf", b"second original", "Changed synthetic background", {"status": "ready"}
    )

    def change_selection():
        profile = profile_store.read_profile()
        profile_store.select_cv(next_cv["id"], expected_revision=profile["revision"])

    model.on_done = change_selection
    section = outline["sections"][0]
    response = client.post(_generate_url(topic, section["id"]), json=_request(outline))

    events = _events(response)
    assert events[-1]["type"] == "error"
    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}").json()
    assert state["assessments"] == []
    assert state["current_assessment"] is None
    assert profile_store.read_proficiency()["entries"] == []


def test_failed_retry_keeps_previous_completed_assessment_current(tmp_path):
    model = PrerequisiteFakeModel()
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]
    first = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))[-1]["assessment"]
    model.behavior = "error"

    failed = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))[-1]

    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}").json()
    assert failed["type"] == "error"
    assert [item["assessment_id"] for item in state["assessments"]] == [first["assessment_id"]]
    assert state["current_assessment"]["assessment_id"] == first["assessment_id"]


def test_final_result_write_failure_leaves_registered_rows_inactive_and_keeps_old_result(tmp_path, monkeypatch):
    import lab.web.prerequisites as prerequisite_routes

    model = PrerequisiteFakeModel()
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]
    first = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))[-1]["assessment"]
    write_attempt = prerequisite_routes.write_prerequisite_attempt

    def fail_completed_write(*args, assessment=None, **kwargs):
        if assessment is not None:
            raise OSError("synthetic final assessment write failure")
        return write_attempt(*args, assessment=assessment, **kwargs)

    monkeypatch.setattr(prerequisite_routes, "write_prerequisite_attempt", fail_completed_write)
    failed = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))[-1]

    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}").json()
    profile = client.app.state.deps.profile_store.read_proficiency()
    assert failed["type"] == "error"
    assert [item["assessment_id"] for item in state["assessments"]] == [first["assessment_id"]]
    assert state["current_assessment"]["assessment_id"] == first["assessment_id"]
    assert len([item for item in profile["entries"] if item["source_kind"] == "model_requirement"]) == 2
    assert all(item["comfort"] is None for item in profile["entries"])


def test_ambiguous_completed_write_is_recognized_as_published_success(tmp_path, monkeypatch):
    import lab.web.prerequisites as prerequisite_routes

    client, topic, outline, _model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    write_attempt = prerequisite_routes.write_prerequisite_attempt

    def publish_then_raise(*args, assessment=None, **kwargs):
        result = write_attempt(*args, assessment=assessment, **kwargs)
        if assessment is not None:
            raise OSError("synthetic post-publish acknowledgement loss")
        return result

    monkeypatch.setattr(prerequisite_routes, "write_prerequisite_attempt", publish_then_raise)
    events = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))
    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}").json()

    assert events[-1]["type"] == "done"
    assert state["attempts"][-1]["status"] == "completed"
    assert state["current_assessment"] is not None
    assert len(client.app.state.deps.profile_store.read_proficiency()["entries"]) == 2


def test_unreadable_state_after_provider_completion_emits_uncertain_error_without_cleanup(tmp_path, monkeypatch):
    import lab.web.prerequisites as prerequisite_routes

    client, topic, outline, _model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    first = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))[-1]["assessment"]
    deps = client.app.state.deps
    write_attempt = prerequisite_routes.write_prerequisite_attempt

    def corrupt_after_provider_done(*args, assessment=None, **kwargs):
        if assessment is not None:
            path = deps.store.file_path(topic, "paper-1.prerequisites.json")
            path.write_text("{unreadable", encoding="utf-8")
            raise OSError("synthetic state readback failure")
        return write_attempt(*args, assessment=assessment, **kwargs)

    monkeypatch.setattr(prerequisite_routes, "write_prerequisite_attempt", corrupt_after_provider_done)
    events = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))
    profile = deps.profile_store.read_proficiency()

    assert events[-1]["type"] == "error"
    assert "attempt" not in events[-1]
    assert len(profile["entries"]) == 4
    assert {entry["assessment_id"] for entry in profile["entries"]} == {
        first["assessment_id"],
        events[0]["attempt"]["assessment_id"],
    }
    assert not deps.locks[topic].locked()
    assert deps.active_prerequisite_attempts == {}


def test_cleanup_never_discards_rows_for_same_assessment_published_by_later_attempt(tmp_path, monkeypatch):
    import lab.web.prerequisites as prerequisite_routes
    from types import SimpleNamespace
    import uuid

    client, topic, outline, _model, cv = _prepared(tmp_path)
    section = outline["sections"][0]
    deps = client.app.state.deps
    assessment_id = _write_generating_attempt(deps.store, topic, outline, section, cv)
    state = deps.store
    from lab.prerequisite_store import get_prerequisite_state, write_prerequisite_attempt

    prior = get_prerequisite_state(state, topic, "paper-1")["attempts"][-1]
    failed_prior = {
        **prior,
        "status": "error",
        "finished_at": "2026-10-13T00:01:00+00:00",
        "diagnostic": "Synthetic earlier attempt failed.",
    }
    write_prerequisite_attempt(state, topic, "paper-1", failed_prior)

    next_ids = iter(["e" * 32, assessment_id])
    original_uuid4 = uuid.uuid4

    def fixed_attempt_id_then_random():
        try:
            return SimpleNamespace(hex=next(next_ids))
        except StopIteration:
            return original_uuid4()

    monkeypatch.setattr(prerequisite_routes.uuid, "uuid4", fixed_attempt_id_then_random)
    section_response = client.post(_generate_url(topic, section["id"]), json=_request(outline))
    assert section_response.status_code == 200

    recovered = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites")
    profile_rows = deps.profile_store.read_proficiency()["entries"]

    assert recovered.status_code == 200
    assert [item["status"] for item in recovered.json()["attempts"]] == ["error", "completed"]
    assert len(profile_rows) == 2
    assert all(item["assessment_id"] == assessment_id for item in profile_rows)


def test_idle_get_marks_orphaned_generation_interrupted_and_discards_only_unpublished_rows(tmp_path):
    client, topic, outline, _model, cv = _prepared(tmp_path)
    section = outline["sections"][0]
    deps = client.app.state.deps
    assessment_id = _write_generating_attempt(deps.store, topic, outline, section, cv)
    _seed_model_requirement(deps.profile_store, cv, topic, assessment_id)

    response = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites")

    assert response.status_code == 200
    assert response.json()["attempts"][-1]["status"] == "interrupted"
    assert response.json()["assessments"] == []
    assert deps.profile_store.read_proficiency()["entries"] == []


def test_unreadable_prerequisite_state_keeps_unpublished_profile_rows_safe(tmp_path):
    client, topic, outline, _model, cv = _prepared(tmp_path)
    assessment_id = "c" * 32
    _seed_model_requirement(client.app.state.deps.profile_store, cv, topic, assessment_id)
    path = client.app.state.deps.store.file_path(topic, "paper-1.prerequisites.json")
    path.write_text("{broken", encoding="utf-8")

    response = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites")

    assert response.status_code == 500
    assert len(client.app.state.deps.profile_store.read_proficiency()["entries"]) == 1


def test_failure_cleanup_preserves_answered_and_noted_rows_written_during_attempt(tmp_path, monkeypatch):
    import lab.web.prerequisites as prerequisite_routes

    client, topic, outline, model, _cv = _prepared(tmp_path)
    response = json.loads(_model_response())
    response["requirements"].append(
        {
            "concept": "Statistics",
            "reason": "The section interprets likelihoods.",
            "source_labels": ["S1"],
            "cv_background": "not_stated",
            "cv_source_labels": [],
            "cv_quote": "",
        }
    )
    model.output = json.dumps(response)
    deps = client.app.state.deps
    section = outline["sections"][0]
    deps.profile_store.add_proficiency(
        concept="Manual Python",
        comfort="refresher",
        notes="Keep my own note",
        expected_revision=0,
    )
    write_attempt = prerequisite_routes.write_prerequisite_attempt

    def edit_rows_then_fail(*args, assessment=None, **kwargs):
        if assessment is not None:
            profile = deps.profile_store.read_proficiency()
            generated = [
                entry for entry in profile["entries"] if entry.get("assessment_id") == assessment["assessment_id"]
            ]
            deps.profile_store.save_proficiency_batch(
                additions=[],
                updates=[
                    {"id": generated[0]["id"], "comfort": "comfortable"},
                    {"id": generated[1]["id"], "notes": "Learner added this"},
                ],
                expected_revision=profile["revision"],
            )
            raise OSError("synthetic unpublished assessment write failure")
        return write_attempt(*args, assessment=assessment, **kwargs)

    monkeypatch.setattr(prerequisite_routes, "write_prerequisite_attempt", edit_rows_then_fail)
    events = _events(client.post(_generate_url(topic, section["id"]), json=_request(outline)))
    profile = deps.profile_store.read_proficiency()
    rows = [entry for entry in profile["entries"] if entry["source_kind"] == "model_requirement"]

    assert events[-1]["type"] == "error"
    assert len(rows) == 2
    assert {entry["comfort"] for entry in rows} == {None, "comfortable"}
    assert {entry["notes"] for entry in rows} == {"", "Learner added this"}
    manual = [entry for entry in profile["entries"] if entry["source_kind"] == "user_manual"]
    assert len(manual) == 1 and manual[0]["notes"] == "Keep my own note"


@pytest.mark.parametrize("phase", ["before_stream", "during_stream"])
def test_cancellation_before_or_during_stream_closes_provider_and_releases_resources(tmp_path, phase):
    model = PrerequisiteFakeModel()
    model.hold_after_token = phase == "during_stream"
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    deps = client.app.state.deps
    section = outline["sections"][0]
    post_route = next(
        route
        for route in prerequisite_router(deps).routes
        if "POST" in route.methods and route.path.endswith("/prerequisites")
    )
    body = PrerequisiteInput(**_request(outline))

    async def scenario():
        response = await post_route.endpoint(topic, "paper-1", section["id"], body)
        if phase == "before_stream":
            from starlette.requests import ClientDisconnect

            async def receive():
                return {"type": "http.disconnect"}

            async def send(_message):
                raise OSError("synthetic disconnect before body")

            with pytest.raises(ClientDisconnect):
                await response(
                    {
                        "type": "http",
                        "asgi": {"spec_version": "2.4"},
                        "method": "POST",
                        "path": "/prerequisites",
                        "headers": [],
                    },
                    receive,
                    send,
                )
            return

        async def receive():
            await asyncio.Event().wait()

        async def send(_message):
            return None

        task = asyncio.create_task(
            response(
                {
                    "type": "http",
                    "asgi": {"spec_version": "2.4"},
                    "method": "POST",
                    "path": "/prerequisites",
                    "headers": [],
                },
                receive,
                send,
            )
        )
        await asyncio.wait_for(model.token_sent.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites").json()
    assert state["attempts"][-1]["status"] == "cancelled"
    assert not deps.locks[topic].locked()
    assert not deps.model_generation_lock.locked()
    assert deps.active_prerequisite_attempts == {}
    if phase == "during_stream":
        assert model.stream_closed
