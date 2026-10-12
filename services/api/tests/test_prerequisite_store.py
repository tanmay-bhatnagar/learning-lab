"""Topic-scoped persistence contracts for generated prerequisite assessments."""

from __future__ import annotations

import hashlib
import json

import pytest

from lab.errors import Conflict, CorruptData, NotFound
from lab.prerequisite_store import (
    current_assessment,
    get_prerequisite_state,
    recover_interrupted_attempts,
    write_prerequisite_attempt,
)
from lab.storage import Store, write_json

MAP_REVISION = "a" * 64
SOURCE_HASH = "b" * 64
CV_ID = "c" * 32
CV_HASH = "d" * 64
POLICY_HASH = "e" * 64


@pytest.fixture
def scoped_store(tmp_path):
    store = Store(tmp_path / "topics", tmp_path / "settings.json")
    topic = store.create("Synthetic prerequisites")
    file_id = "synthetic-paper"
    write_json(
        store.topic(topic["id"]) / "files.json",
        [{"id": file_id, "name": "synthetic.pdf", "status": "ready"}],
    )
    return store, topic["id"], file_id


def _attempt(*, attempt_id="attempt-1", assessment_id="assessment-1", status="generating", finished_at=None):
    return {
        "id": attempt_id,
        "assessment_id": assessment_id,
        "topic_id": "synthetic-topic",
        "file_id": "synthetic-paper",
        "map_revision": MAP_REVISION,
        "section_id": "section-1",
        "status": status,
        "started_at": "2026-10-13T10:00:00+00:00",
        "finished_at": finished_at,
        "provenance": {
            "prompt_version": "section-prerequisites-v1",
            "source_sha256": SOURCE_HASH,
            "runtime_policy_sha256": POLICY_HASH,
            "cv_id": CV_ID,
            "cv_text_sha256": CV_HASH,
            "goal": "Understand synthetic section",
            "model": "local-model",
        },
        "diagnostic": None,
    }


def _assessment(*, attempt_id="attempt-1", assessment_id="assessment-1"):
    return {
        "attempt_id": attempt_id,
        "assessment_id": assessment_id,
        "topic_id": "synthetic-topic",
        "file_id": "synthetic-paper",
        "map_revision": MAP_REVISION,
        "section_id": "section-1",
        "cv_id": CV_ID,
        "cv_text_sha256": CV_HASH,
        "source_sha256": SOURCE_HASH,
        "overview": "A concise overview.",
        "requirements": [
            {
                "requirement_id": "req-" + hashlib.sha256(b"assessment-1:0").hexdigest()[:24],
                "concept": "Basic programming",
                "reason": "The section describes an algorithm.",
                "question": "Are you already comfortable with Basic programming?",
                "source_labels": ["S1"],
                "cv_background": "not_stated",
                "cv_source_labels": [],
                "cv_quote": "",
                "comfort": None,
                "comfort_status": "pending",
            }
        ],
        "sources": [{"label": "S1", "unit_id": "unit-1", "source_refs": ["p1"], "pages": [1]}],
        "finished_at": "2026-10-13T10:01:00+00:00",
    }


def _write(store, topic_id, file_id, attempt, assessment=None):
    attempt = {**attempt, "topic_id": topic_id}
    if assessment is not None:
        assessment = {**assessment, "topic_id": topic_id}
    return write_prerequisite_attempt(store, topic_id, file_id, attempt, assessment=assessment)


def _complete(store, topic_id, file_id, attempt=None, assessment=None):
    attempt = attempt or _attempt()
    _write(store, topic_id, file_id, attempt)
    completed = {**attempt, "status": "completed", "finished_at": "2026-10-13T10:01:00+00:00"}
    return _write(store, topic_id, file_id, completed, assessment or _assessment())


def test_missing_state_is_empty_and_topic_local(scoped_store):
    store, topic_id, file_id = scoped_store

    state = get_prerequisite_state(store, topic_id, file_id)

    assert state == {
        "schema_version": 1,
        "topic_id": topic_id,
        "file_id": file_id,
        "attempts": [],
        "assessments": [],
    }
    with pytest.raises(NotFound):
        get_prerequisite_state(store, "another-topic", file_id)


def test_completed_assessment_is_immutable_and_excludes_prompt_material(scoped_store):
    store, topic_id, file_id = scoped_store
    attempt = _attempt()
    assessment = _assessment()

    completed = {**attempt, "status": "completed", "finished_at": "2026-10-13T10:01:00+00:00"}
    _complete(store, topic_id, file_id, attempt, assessment)
    replay = _write(store, topic_id, file_id, completed, assessment)

    expected = {**assessment, "topic_id": topic_id}
    assert replay["assessments"] == [expected]
    raw = (store.topic(topic_id) / f"{file_id}.prerequisites.json").read_text(encoding="utf-8")
    assert "complete-cv" not in raw
    assert "runtime-policy" not in raw
    assert '"messages"' not in raw
    with pytest.raises(Conflict):
        _write(
            store,
            topic_id,
            file_id,
            {**attempt, "status": "completed", "finished_at": assessment["finished_at"]},
            {**assessment, "overview": "changed"},
        )


def test_new_failed_attempt_does_not_replace_last_completed_assessment(scoped_store):
    store, topic_id, file_id = scoped_store
    completed = _attempt()
    _complete(store, topic_id, file_id, completed, _assessment())

    failed = _attempt(
        attempt_id="attempt-2",
        assessment_id="assessment-2",
    )
    _write(store, topic_id, file_id, failed)
    failed = {**failed, "status": "error", "finished_at": "2026-10-13T10:03:00+00:00"}
    failed["diagnostic"] = "Synthetic model error"
    state = _write(store, topic_id, file_id, failed)

    assert len(state["assessments"]) == 1
    expected = {**_assessment(), "topic_id": topic_id}
    assert (
        current_assessment(
            state,
            map_revision=MAP_REVISION,
            section_id="section-1",
            cv_id=CV_ID,
            cv_text_sha256=CV_HASH,
        )
        == expected
    )


def test_generating_attempt_cannot_publish_partial_assessment(scoped_store):
    store, topic_id, file_id = scoped_store

    with pytest.raises(CorruptData):
        _write(store, topic_id, file_id, _attempt(), _assessment())
    assert get_prerequisite_state(store, topic_id, file_id)["assessments"] == []


@pytest.mark.parametrize(
    "change",
    [
        lambda assessment: assessment["requirements"][0].update(question="Tell me about programming."),
        lambda assessment: assessment["requirements"][0].update(source_labels=["S2"]),
        lambda assessment: assessment["requirements"][0].update(comfort="comfortable"),
        lambda assessment: assessment.update(cv_text="literal CV must not be stored"),
        lambda assessment: assessment.update(runtime_policy="policy text must not be stored"),
    ],
    ids=["question", "source-reference", "comfort", "full-cv", "policy"],
)
def test_invalid_or_prompt_bearing_assessment_cannot_be_published(scoped_store, change):
    store, topic_id, file_id = scoped_store
    attempt = _attempt()
    _write(store, topic_id, file_id, attempt)
    completed = {**attempt, "status": "completed", "finished_at": "2026-10-13T10:01:00+00:00"}
    assessment = _assessment()
    change(assessment)

    with pytest.raises(CorruptData):
        _write(store, topic_id, file_id, completed, assessment)
    state = get_prerequisite_state(store, topic_id, file_id)
    assert state["assessments"] == []
    assert state["attempts"][0]["status"] == "generating"


def test_current_assessment_requires_exact_scope_and_source_version(scoped_store):
    store, topic_id, file_id = scoped_store
    _complete(store, topic_id, file_id)
    state = get_prerequisite_state(store, topic_id, file_id)

    assert current_assessment(
        state,
        map_revision=MAP_REVISION,
        section_id="section-1",
        cv_id=CV_ID,
        cv_text_sha256=CV_HASH,
    ) == {**_assessment(), "topic_id": topic_id}
    assert (
        current_assessment(
            state,
            map_revision="f" * 64,
            section_id="section-1",
            cv_id=CV_ID,
            cv_text_sha256=CV_HASH,
        )
        is None
    )


def test_zero_requirements_is_a_valid_completed_assessment(scoped_store):
    store, topic_id, file_id = scoped_store
    assessment = _assessment()
    assessment["requirements"] = []

    state = _complete(store, topic_id, file_id, assessment=assessment)

    assert state["assessments"][0]["requirements"] == []
    assert (
        current_assessment(
            state,
            map_revision=MAP_REVISION,
            section_id="other-section",
            cv_id=CV_ID,
            cv_text_sha256=CV_HASH,
        )
        is None
    )
    assert (
        current_assessment(
            state,
            map_revision=MAP_REVISION,
            section_id="section-1",
            cv_id=CV_ID,
            cv_text_sha256="f" * 64,
        )
        is None
    )


def test_corrupt_unsupported_and_cross_file_state_blocks_read(scoped_store):
    store, topic_id, file_id = scoped_store
    path = store.topic(topic_id) / f"{file_id}.prerequisites.json"
    path.write_text('{"schema_version": 99}', encoding="utf-8")

    with pytest.raises(CorruptData):
        get_prerequisite_state(store, topic_id, file_id)

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "topic_id": topic_id,
                "file_id": "other-file",
                "attempts": [],
                "assessments": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CorruptData):
        get_prerequisite_state(store, topic_id, file_id)


def test_interrupted_recovery_preserves_active_attempts(scoped_store):
    store, topic_id, file_id = scoped_store
    active = _attempt(attempt_id="active-attempt", assessment_id="assessment-active")
    abandoned = _attempt(attempt_id="abandoned-attempt", assessment_id="assessment-abandoned")
    active["topic_id"] = topic_id
    abandoned["topic_id"] = topic_id
    state = {
        "schema_version": 1,
        "topic_id": topic_id,
        "file_id": file_id,
        "attempts": [active, abandoned],
        "assessments": [],
    }
    write_json(store.topic(topic_id) / f"{file_id}.prerequisites.json", state)

    changed = recover_interrupted_attempts(
        store,
        topic_id,
        file_id,
        active_attempt_ids={"active-attempt"},
        finished_at="2026-10-13T11:00:00+00:00",
    )
    recovered = get_prerequisite_state(store, topic_id, file_id)

    assert changed is True
    statuses = {item["id"]: item["status"] for item in recovered["attempts"]}
    assert statuses == {"active-attempt": "generating", "abandoned-attempt": "interrupted"}


def test_duplicate_attempt_id_with_different_content_is_conflict(scoped_store):
    store, topic_id, file_id = scoped_store
    original = _attempt()
    _write(store, topic_id, file_id, original)

    with pytest.raises(Conflict):
        _write(store, topic_id, file_id, {**original, "section_id": "different-section"})


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("started_at", "2026-10-13T10:00:01+00:00"),
        ("goal", "A different goal"),
        ("model", "another-local-model"),
        ("runtime_policy_sha256", "f" * 64),
        ("prompt_version", "another-prompt"),
    ],
)
def test_finishing_attempt_preserves_original_request_metadata(scoped_store, field, replacement):
    store, topic_id, file_id = scoped_store
    generating = _attempt()
    _write(store, topic_id, file_id, generating)
    completed = {
        **generating,
        "status": "completed",
        "finished_at": "2026-10-13T10:01:00+00:00",
    }
    if field in {"started_at"}:
        completed[field] = replacement
    else:
        completed["provenance"] = {**generating["provenance"], field: replacement}

    with pytest.raises(Conflict):
        _write(store, topic_id, file_id, completed, _assessment())


def test_corrupt_second_completed_attempt_requires_its_exact_result_link(scoped_store):
    store, topic_id, file_id = scoped_store
    _complete(store, topic_id, file_id)
    path = store.topic(topic_id) / f"{file_id}.prerequisites.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    second_attempt = _attempt(attempt_id="attempt-2")
    second_attempt.update(
        {
            "topic_id": topic_id,
            "status": "completed",
            "finished_at": "2026-10-13T10:01:00+00:00",
        }
    )
    state["attempts"].append(second_attempt)
    write_json(path, state)

    with pytest.raises(CorruptData):
        get_prerequisite_state(store, topic_id, file_id)


@pytest.mark.parametrize("hash_field", ["source_sha256", "runtime_policy_sha256", "cv_text_sha256"])
def test_corrupt_state_requires_hash_values_to_be_strings(scoped_store, hash_field):
    store, topic_id, file_id = scoped_store
    _write(store, topic_id, file_id, _attempt())
    path = store.topic(topic_id) / f"{file_id}.prerequisites.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["attempts"][0]["provenance"][hash_field] = int("1" * 64)
    write_json(path, state)

    with pytest.raises(CorruptData):
        get_prerequisite_state(store, topic_id, file_id)
