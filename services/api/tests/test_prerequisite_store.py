"""Topic-scoped persistence contracts for generated prerequisite assessments."""

from __future__ import annotations

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
        "overview": "A concise overview.",
        "requirements": [
            {
                "requirement_id": "req-one",
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
    attempt = _attempt(status="completed", finished_at="2026-10-13T10:01:00+00:00")
    assessment = _assessment()

    _write(store, topic_id, file_id, attempt, assessment)
    replay = _write(store, topic_id, file_id, attempt, assessment)

    assert replay["assessments"] == [assessment]
    raw = (store.topic(topic_id) / f"{file_id}.prerequisites.json").read_text(encoding="utf-8")
    assert "complete-cv" not in raw
    assert "runtime-policy" not in raw
    assert '"messages"' not in raw
    with pytest.raises(Conflict):
        _write(store, topic_id, file_id, attempt, {**assessment, "overview": "changed"})


def test_new_failed_attempt_does_not_replace_last_completed_assessment(scoped_store):
    store, topic_id, file_id = scoped_store
    completed = _attempt(status="completed", finished_at="2026-10-13T10:01:00+00:00")
    _write(store, topic_id, file_id, completed, _assessment())

    failed = _attempt(
        attempt_id="attempt-2",
        assessment_id="assessment-2",
        status="error",
        finished_at="2026-10-13T10:03:00+00:00",
    )
    failed["diagnostic"] = "Synthetic model error"
    state = _write(store, topic_id, file_id, failed)

    assert len(state["assessments"]) == 1
    assert (
        current_assessment(
            state,
            map_revision=MAP_REVISION,
            section_id="section-1",
            cv_id=CV_ID,
            cv_text_sha256=CV_HASH,
        )
        == _assessment()
    )


def test_generating_attempt_cannot_publish_partial_assessment(scoped_store):
    store, topic_id, file_id = scoped_store

    with pytest.raises(CorruptData):
        _write(store, topic_id, file_id, _attempt(), _assessment())
    assert get_prerequisite_state(store, topic_id, file_id)["assessments"] == []


def test_current_assessment_requires_exact_scope_and_source_version(scoped_store):
    store, topic_id, file_id = scoped_store
    _write(
        store,
        topic_id,
        file_id,
        _attempt(status="completed", finished_at="2026-10-13T10:01:00+00:00"),
        _assessment(),
    )
    state = get_prerequisite_state(store, topic_id, file_id)

    assert (
        current_assessment(
            state,
            map_revision=MAP_REVISION,
            section_id="section-1",
            cv_id=CV_ID,
            cv_text_sha256=CV_HASH,
        )
        == _assessment()
    )
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
