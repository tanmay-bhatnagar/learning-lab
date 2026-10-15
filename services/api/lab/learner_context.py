"""Fresh, compact learner context assembled at each chat request boundary."""

from __future__ import annotations

from typing import Any

from lab.conversation_profile import get_conversation_profile
from lab.conversation_profile import validate_conversation_profile
from lab.errors import Conflict, CorruptData
from lab.learner_profile import proficiency_context
from lab.prerequisite_store import get_prerequisite_state
from lab.profile_store import ProfileStore
from lab.storage import Store


def selected_cv_snapshot(profile_store: ProfileStore) -> tuple[str, str]:
    """Read one eligible active CV as complete canonical extracted text with integrity checks."""
    before = profile_store.read_profile()
    cv_id = before["active_cv_id"]
    record = next((candidate for candidate in before["cvs"] if candidate["id"] == cv_id), None)
    if record is None or record["status"] != "ready" or record["revoked"]:
        raise Conflict("Select an available, successfully extracted CV before including it in chat.")
    text = profile_store.read_extracted_text(cv_id)
    after = profile_store.read_profile()
    if after["revision"] != before["revision"] or after["active_cv_id"] != cv_id:
        raise Conflict("The selected CV changed while it was being loaded; retry the chat request.")
    if not text.strip():
        raise Conflict("The selected CV has no extracted text available to include.")
    return text, record["original_name"]


def _active_assessment(store: Store, topic_id: str, focus: dict[str, Any]) -> dict[str, Any]:
    state = get_prerequisite_state(store, topic_id, focus["file_id"])
    assessment = next(
        (
            item
            for item in state["assessments"]
            if item["assessment_id"] == focus["assessment_id"]
            and item["topic_id"] == topic_id
            and item["file_id"] == focus["file_id"]
            and item["map_revision"] == focus["map_revision"]
            and item["section_id"] == focus["section_id"]
        ),
        None,
    )
    if assessment is None:
        raise Conflict("The selected learning assessment is no longer available; choose it again from the source.")
    attempt = next((item for item in state["attempts"] if item["id"] == assessment["attempt_id"]), None)
    if (
        attempt is None
        or attempt["status"] != "completed"
        or attempt["assessment_id"] != focus["assessment_id"]
        or attempt["topic_id"] != topic_id
        or attempt["file_id"] != focus["file_id"]
        or attempt["map_revision"] != focus["map_revision"]
        or attempt["section_id"] != focus["section_id"]
        or attempt["provenance"]["goal"] != focus["goal"]
    ):
        raise Conflict("The selected learning assessment does not match its completed generation record.")
    return assessment


def _project_context(
    proficiency: dict[str, Any],
    *,
    topic_id: str,
    focus: dict[str, Any] | None,
    assessment: dict[str, Any] | None,
) -> str:
    assessment_id = focus["assessment_id"] if focus is not None else None
    if focus is not None and assessment is not None:
        _validate_selected_assessment_rows(proficiency, topic_id=topic_id, assessment=assessment)
    current_self_reports = proficiency_context(
        proficiency,
        topic_id=topic_id,
        active_assessment_id=assessment_id,
    )
    if focus is None or assessment is None:
        return current_self_reports
    lines = [
        "Selected-section learning context (model-proposed prerequisites are unverified and are not mastery claims):",
        f"Focus: document {focus['file_id']}, section {focus['section_id']}",
        f"Goal: {focus['goal']}",
        f"Overview: {assessment['overview']}",
        "Preparatory concepts:",
    ]
    requirements = assessment["requirements"]
    if not requirements:
        lines.append("- None proposed.")
    else:
        for requirement in requirements:
            lines.append(f"- {requirement['concept']}: {requirement['reason']}")
    if current_self_reports:
        lines.extend(["", current_self_reports])
    return "\n".join(lines)


def _validate_selected_assessment_rows(
    proficiency: dict[str, Any],
    *,
    topic_id: str,
    assessment: dict[str, Any],
) -> None:
    """Require exact, complete My proficiency links for only this selected assessment."""
    expected = {item["requirement_id"]: item["concept"] for item in assessment["requirements"]}
    found: set[str] = set()
    for entry in proficiency["entries"]:
        if (
            entry["source_kind"] != "model_requirement"
            or entry["topic_id"] != topic_id
            or entry["assessment_id"] != assessment["assessment_id"]
        ):
            continue
        requirement_id = entry["requirement_id"]
        if requirement_id not in expected or entry["concept"] != expected[requirement_id]:
            raise CorruptData("My proficiency contains a requirement link that does not match this assessment.")
        if requirement_id in found:
            raise CorruptData("My proficiency contains duplicate rows for this assessment requirement.")
        found.add(requirement_id)
    if found != set(expected):
        raise CorruptData("My proficiency is missing a requirement row for this completed assessment.")


def load_learner_context(
    store: Store,
    profile_store: ProfileStore,
    topic_id: str,
    conversation_id: str,
    *,
    pinned_preferences: dict[str, Any] | None = None,
) -> dict[str, str | None]:
    """Reload preferences, current self-reports, historical focus and optional full CV for this turn."""
    preferences = (
        get_conversation_profile(store, topic_id, conversation_id)
        if pinned_preferences is None
        else validate_conversation_profile(pinned_preferences)
    )
    proficiency = profile_store.read_proficiency()
    focus = preferences["active_assessment"]
    assessment = _active_assessment(store, topic_id, focus) if focus is not None else None
    context = _project_context(
        proficiency,
        topic_id=topic_id,
        focus=focus,
        assessment=assessment,
    )
    cv_text: str | None = None
    cv_name: str | None = None
    if preferences["include_cv"]:
        cv_text, cv_name = selected_cv_snapshot(profile_store)
    return {"learner_context": context, "cv_text": cv_text, "cv_name": cv_name}
