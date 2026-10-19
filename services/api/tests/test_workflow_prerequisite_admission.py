"""LangGraph prerequisite admission graph tests."""

from __future__ import annotations

import hashlib
import json

import pytest

from lab.errors import Conflict, DoesNotFit
from lab.prerequisite_store import get_prerequisite_state, write_prerequisite_attempt
from lab.workflows.prerequisites import (
    PREREQUISITE_ADMISSION_MERMAID,
    PrerequisiteAdmissionCapabilities,
    admit_prerequisite_generation,
    admission_callables_are_coroutines,
    compile_prerequisite_admission_graph,
    recover_file_state,
)
from tests.test_web_prerequisites import (
    PrerequisiteFakeModel,
    _generate_url,
    _prepared,
    _request,
    _seed_model_requirement,
    _write_generating_attempt,
)


def _admission_capabilities(deps, topic: str, file_id: str, revision: str, section_id: str):
    registered: list[str] = []

    def register_active(attempt_id: str) -> None:
        registered.append(attempt_id)
        from lab.web.deps import ActivePrerequisite

        deps.active_prerequisite_attempts[attempt_id] = ActivePrerequisite(
            topic=topic,
            file_id=file_id,
            revision=revision,
            section_id=section_id,
        )

    return (
        PrerequisiteAdmissionCapabilities(
            store=deps.store,
            profile_store=deps.profile_store,
            runtime_policy_path=deps.config.runtime_policy_path,
            now=lambda: "2026-10-20T00:00:00+00:00",
            new_attempt_ids=lambda: (hashlib.sha256(b"a").hexdigest(), hashlib.sha256(b"b").hexdigest()),
            register_active=register_active,
        ),
        registered,
    )


async def _admit(client, topic, outline, section, body, *, model: PrerequisiteFakeModel | None = None):
    deps = client.app.state.deps
    gateway = model or deps.model_backend
    assert isinstance(gateway, PrerequisiteFakeModel)
    caps, registered = _admission_capabilities(deps, topic, "paper-1", body["revision"], section["id"])
    graph = compile_prerequisite_admission_graph()
    return (
        await admit_prerequisite_generation(
            graph,
            capabilities=caps,
            topic_id=topic,
            file_id="paper-1",
            section_id=section["id"],
            revision=body["revision"],
            model=body["model"],
            context_limit=body["context_limit"],
            think=body.get("think"),
            goal=body.get("goal"),
            active_attempt_ids=set(),
        ),
        gateway,
        registered,
    )


@pytest.mark.anyio
async def test_admission_mermaid_documents_node_names() -> None:
    for name in (
        "recover_and_reconcile",
        "resolve_map",
        "select_cv",
        "load_policy",
        "plan_fit",
        "write_generating_attempt",
    ):
        assert name in PREREQUISITE_ADMISSION_MERMAID


def test_admission_graph_callables_are_async() -> None:
    assert admission_callables_are_coroutines()


@pytest.mark.anyio
@pytest.mark.parametrize("revoked", [False, True], ids=["missing-cv", "revoked-cv"])
async def test_missing_or_revoked_cv_conflicts_without_model_or_attempt(tmp_path, revoked: bool) -> None:
    if revoked:
        client, topic, outline, model, cv = _prepared(tmp_path)
        profile = client.app.state.deps.profile_store.read_profile()
        client.app.state.deps.profile_store.revoke_cv(cv["id"], expected_revision=profile["revision"])
    else:
        client, topic, outline, model, _cv = _prepared(tmp_path, cv_text=None)
    section = outline["sections"][0]
    body = _request(outline)

    with pytest.raises(Conflict):
        (await _admit(client, topic, outline, section, body, model=model))[0]

    assert model.requests == []
    state = get_prerequisite_state(client.app.state.deps.store, topic, "paper-1")
    assert state["attempts"] == []
    response = client.post(_generate_url(topic, section["id"]), json=body)
    assert response.status_code == 409
    assert not client.app.state.deps.locks[topic].locked()


@pytest.mark.anyio
async def test_cv_text_hash_mismatch_conflicts_without_attempt(tmp_path, monkeypatch) -> None:
    client, topic, outline, model, cv = _prepared(tmp_path)
    section = outline["sections"][0]
    body = _request(outline)
    profile_store = client.app.state.deps.profile_store
    original_read = profile_store.read_extracted_text

    def mismatched_text(cv_id: str) -> str:
        return original_read(cv_id) + " "

    monkeypatch.setattr(profile_store, "read_extracted_text", mismatched_text)

    with pytest.raises(Conflict, match="CV text changed"):
        (await _admit(client, topic, outline, section, body, model=model))[0]

    assert model.requests == []
    assert get_prerequisite_state(client.app.state.deps.store, topic, "paper-1")["attempts"] == []


@pytest.mark.anyio
async def test_stale_map_revision_conflicts_without_attempt(tmp_path) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    body = {**_request(outline), "revision": "f" * 64}

    with pytest.raises(Conflict, match="revision changed"):
        (await _admit(client, topic, outline, section, body, model=model))[0]

    assert model.requests == []
    assert get_prerequisite_state(client.app.state.deps.store, topic, "paper-1")["attempts"] == []


@pytest.mark.anyio
async def test_oversized_whole_input_refuses_before_generating_attempt(tmp_path) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path, cv_text="X" * 12000)
    section = outline["sections"][0]
    body = {**_request(outline), "context_limit": 1024}

    with pytest.raises(DoesNotFit):
        (await _admit(client, topic, outline, section, body, model=model))[0]

    assert model.requests == []
    assert get_prerequisite_state(client.app.state.deps.store, topic, "paper-1")["attempts"] == []


@pytest.mark.anyio
async def test_admission_plan_includes_full_section_cv_goal_and_policy(tmp_path) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path, policy="Synthetic full runtime policy.")
    section = outline["sections"][0]
    body = _request(outline)
    admitted, gateway, registered = await _admit(client, topic, outline, section, body, model=model)

    assert gateway.requests == []
    assert len(registered) == 1
    messages = admitted.plan["messages"]
    assert len(messages) == 2
    assert messages[0]["content"].count("Synthetic full runtime policy.") == 1
    assert messages[1]["content"].count("Synthetic CV evidence.") == 1
    assert "Synthetic algorithms describe probability." in messages[1]["content"]
    assert "CHAT HISTORY SENTINEL" not in json.dumps(messages)
    assert "TOPIC GOAL" not in json.dumps(messages)
    assert body["goal"] in json.dumps(messages)


@pytest.mark.anyio
async def test_admission_never_calls_stream_chat(tmp_path) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    body = _request(outline)
    await _admit(client, topic, outline, section, body, model=model)
    assert model.requests == []


@pytest.mark.anyio
async def test_recovery_reconciles_orphaned_pending_while_preserving_manual_and_published(tmp_path) -> None:
    client, topic, outline, _model, cv = _prepared(tmp_path)
    section = outline["sections"][0]
    deps = client.app.state.deps
    profile_store = deps.profile_store
    profile_store.add_proficiency(
        concept="Manual Python",
        comfort="refresher",
        notes="Keep manual",
        expected_revision=0,
    )
    done = client.post(_generate_url(topic, section["id"]), json=_request(outline))
    published_assessment_id = json.loads(done.text.splitlines()[-1])["assessment"]["assessment_id"]
    published_rows = profile_store.read_proficiency()["entries"]
    answered = next(entry for entry in published_rows if entry.get("assessment_id") == published_assessment_id)
    profile_store.save_proficiency_batch(
        additions=[],
        updates=[{"id": answered["id"], "comfort": "comfortable", "notes": "answered note"}],
        expected_revision=profile_store.read_proficiency()["revision"],
    )

    orphan_assessment = _write_generating_attempt(deps.store, topic, outline, section, cv)
    _seed_model_requirement(profile_store, cv, topic, orphan_assessment, concept="Orphan pending")

    body = _request(outline)
    await _admit(client, topic, outline, section, body)

    state = get_prerequisite_state(deps.store, topic, "paper-1")
    statuses = [item["status"] for item in state["attempts"]]
    assert statuses.count("completed") == 1
    assert statuses.count("interrupted") == 1
    assert statuses[-1] == "generating"
    profile = profile_store.read_proficiency()
    manual = [entry for entry in profile["entries"] if entry["source_kind"] == "user_manual"]
    published = [entry for entry in profile["entries"] if entry.get("assessment_id") == published_assessment_id]
    orphan_rows = [entry for entry in profile["entries"] if entry.get("assessment_id") == orphan_assessment]
    assert len(manual) == 1 and manual[0]["notes"] == "Keep manual"
    assert len(published) == 2
    assert published[0]["comfort"] == "comfortable"
    assert orphan_rows == []


@pytest.mark.anyio
async def test_recover_file_state_byte_identical_to_workflow_helper(tmp_path) -> None:
    client, topic, outline, _model, cv = _prepared(tmp_path)
    section = outline["sections"][0]
    deps = client.app.state.deps
    assessment_id = _write_generating_attempt(deps.store, topic, outline, section, cv)
    _seed_model_requirement(deps.profile_store, cv, topic, assessment_id)

    recover_file_state(deps.store, deps.profile_store, topic, "paper-1", set(), now=lambda: "2026-10-20T00:00:00+00:00")

    state = get_prerequisite_state(deps.store, topic, "paper-1")
    assert state["attempts"][-1]["status"] == "interrupted"
    assert deps.profile_store.read_proficiency()["entries"] == []
