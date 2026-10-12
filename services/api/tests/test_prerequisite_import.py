from copy import deepcopy

import pytest

from lab.errors import CorruptData
from lab.prerequisite_import import (
    build_prerequisite_import,
    existing_prerequisite_import,
    validated_prerequisite_imports,
)


def _assessment():
    return {
        "assessment_id": "assessment-1",
        "attempt_id": "attempt-1",
        "topic_id": "topic-one",
        "file_id": "paper",
        "map_revision": "a" * 64,
        "section_id": "methods",
        "finished_at": "2026-10-13T00:00:00+00:00",
        "overview": "Basic algebra helps.",
        "requirements": [
            {
                "requirement_id": "req-abc",
                "concept": "Basic algebra",
                "reason": "Read equations.",
                "source_labels": ["S1"],
            }
        ],
        "sources": [{"label": "S1", "unit_id": "unit-one", "source_refs": ["#/texts/1"], "pages": [1]}],
    }


def _message(conversation_id="default"):
    return build_prerequisite_import(
        conversation_id,
        assessment=_assessment(),
        section_title="Methods",
        goal="Understand the method",
        model="local-model",
        learner_context="Basic algebra: needs a refresher (self-reported).",
        imported_at="2026-10-13T00:01:00+00:00",
    )


def test_import_is_visible_immutable_snapshot_without_model_or_cv_text():
    source = _assessment()
    before = deepcopy(source)
    message = _message()
    assert message["role"] == "user"
    assert "Saved prerequisites — Methods" in message["content"]
    assert "Basic algebra" in message["content"]
    assert "needs a refresher" in message["content"]
    assert "model-inferred" in message["content"]
    assert source == before
    assert "cv_text" not in message["prerequisite_import"]
    assert message["prerequisite_import"]["goal"] == "Understand the method"


def test_destination_bound_idempotent_import_preserves_original_snapshot():
    message = _message()
    session = {"messages": [message]}
    before = deepcopy(session)
    assert existing_prerequisite_import(session, "default", assessment_id="assessment-1", file_id="paper") == message
    assert session == before
    assert _message("other-chat")["prerequisite_import"]["import_id"] != message["prerequisite_import"]["import_id"]
    assert existing_prerequisite_import(session, "default", assessment_id="assessment-2", file_id="paper") is None


@pytest.mark.parametrize("mutation", ["content", "destination", "version", "role"])
def test_corrupt_import_metadata_or_snapshot_is_not_silently_accepted(mutation):
    message = _message()
    if mutation == "content":
        message["content"] += "\nTampered snapshot"
    if mutation == "destination":
        message["prerequisite_import"]["conversation_id"] = "other-chat"
    if mutation == "version":
        message["prerequisite_import"]["schema_version"] = 2
    if mutation == "role":
        message["role"] = "assistant"
    with pytest.raises(CorruptData):
        validated_prerequisite_imports({"messages": [message]}, "default")


def test_legacy_messages_remain_valid_and_are_not_migrated():
    session = {"messages": [{"role": "user", "content": "ordinary history"}]}
    before = deepcopy(session)
    assert validated_prerequisite_imports(session, "default") == []
    assert session == before
