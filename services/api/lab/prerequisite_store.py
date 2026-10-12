"""Validated topic-scoped persistence for prerequisite attempts and assessments."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import os
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from lab.errors import Conflict, CorruptData, NotFound
from lab.storage import Store, checked, read_json, valid_id, write_json

PREREQUISITE_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CV_ID = re.compile(r"^[a-f0-9]{32}$")
_REQUIREMENT_ID = re.compile(r"^req-[a-f0-9]{24}$")
_ATTEMPT_STATUSES = {"generating", "completed", "cancelled", "error", "interrupted"}
_ATTEMPT_FIELDS = {
    "id",
    "assessment_id",
    "topic_id",
    "file_id",
    "map_revision",
    "section_id",
    "status",
    "started_at",
    "finished_at",
    "provenance",
    "diagnostic",
}
_PROVENANCE_FIELDS = {
    "prompt_version",
    "source_sha256",
    "runtime_policy_sha256",
    "cv_id",
    "cv_text_sha256",
    "goal",
    "model",
}
_ASSESSMENT_FIELDS = {
    "attempt_id",
    "assessment_id",
    "topic_id",
    "file_id",
    "map_revision",
    "section_id",
    "cv_id",
    "cv_text_sha256",
    "source_sha256",
    "overview",
    "requirements",
    "sources",
    "finished_at",
}
_REQUIREMENT_FIELDS = {
    "requirement_id",
    "concept",
    "reason",
    "question",
    "source_labels",
    "cv_background",
    "cv_source_labels",
    "cv_quote",
    "comfort",
    "comfort_status",
}
_SOURCE_FIELDS = {"label", "unit_id", "source_refs", "pages"}


def prerequisite_filename(file_id: str) -> str:
    """Return the deterministic prerequisite-state name for a validated file ID."""
    return f"{valid_id(file_id)}.prerequisites.json"


def empty_prerequisite_state(topic_id: str, file_id: str) -> dict[str, Any]:
    """Return an empty state bound to one validated topic and file."""
    return {
        "schema_version": PREREQUISITE_SCHEMA_VERSION,
        "topic_id": valid_id(topic_id),
        "file_id": valid_id(file_id),
        "attempts": [],
        "assessments": [],
    }


def validate_prerequisite_state(value: object, *, topic_id: str, file_id: str) -> dict[str, Any]:
    """Validate the exact stored schema and all cross-record identities."""
    expected_topic = valid_id(topic_id)
    expected_file = valid_id(file_id)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "topic_id", "file_id", "attempts", "assessments"}
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != PREREQUISITE_SCHEMA_VERSION
        or value.get("topic_id") != expected_topic
        or value.get("file_id") != expected_file
        or not isinstance(value.get("attempts"), list)
        or not isinstance(value.get("assessments"), list)
    ):
        raise CorruptData("Saved prerequisites are unsupported or belong to a different topic or file.")

    attempts = [_validate_attempt(item, expected_topic, expected_file) for item in value["attempts"]]
    assessments = [_validate_assessment(item, expected_topic, expected_file) for item in value["assessments"]]
    attempt_ids = [item["id"] for item in attempts]
    assessment_ids = [item["assessment_id"] for item in assessments]
    if len(attempt_ids) != len(set(attempt_ids)) or len(assessment_ids) != len(set(assessment_ids)):
        raise CorruptData("Saved prerequisites contain duplicate attempt or assessment identities.")
    attempts_by_id = {item["id"]: item for item in attempts}
    for assessment in assessments:
        attempt = attempts_by_id.get(assessment["attempt_id"])
        if (
            attempt is None
            or attempt["status"] != "completed"
            or attempt["assessment_id"] != assessment["assessment_id"]
            or attempt["finished_at"] != assessment["finished_at"]
            or _assessment_identity(assessment) != _attempt_source_identity(attempt)
        ):
            raise CorruptData("Saved prerequisite assessment does not match its completed attempt.")
    for attempt in attempts:
        if attempt["status"] == "completed":
            linked = next(
                (
                    item
                    for item in assessments
                    if item["attempt_id"] == attempt["id"] and item["assessment_id"] == attempt["assessment_id"]
                ),
                None,
            )
            if linked is None:
                raise CorruptData("Completed prerequisite attempt has no exactly linked assessment.")
    return {
        "schema_version": PREREQUISITE_SCHEMA_VERSION,
        "topic_id": expected_topic,
        "file_id": expected_file,
        "attempts": attempts,
        "assessments": assessments,
    }


def get_prerequisite_state(store: Store, topic_id: str, file_id: str) -> dict[str, Any]:
    """Read the validated state for an existing ready topic attachment."""
    _require_ready_file(store, topic_id, file_id)
    path = store.file_path(topic_id, prerequisite_filename(file_id))
    state = read_json(path, empty_prerequisite_state(topic_id, file_id))
    return validate_prerequisite_state(state, topic_id=topic_id, file_id=file_id)


def write_prerequisite_attempt(
    store: Store,
    topic_id: str,
    file_id: str,
    attempt: dict[str, Any],
    *,
    assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one lifecycle transition and, only on completion, its matching immutable assessment."""
    _require_ready_file(store, topic_id, file_id)
    topic_id = valid_id(topic_id)
    file_id = valid_id(file_id)
    checked_attempt = _validate_attempt(attempt, topic_id, file_id)
    checked_assessment = _validate_assessment(assessment, topic_id, file_id) if assessment is not None else None
    if (checked_attempt["status"] == "completed") != (checked_assessment is not None):
        raise CorruptData("Only a completed prerequisite attempt can publish its matching assessment.")
    if checked_assessment is not None and (
        checked_assessment["attempt_id"] != checked_attempt["id"]
        or checked_assessment["assessment_id"] != checked_attempt["assessment_id"]
        or checked_assessment["finished_at"] != checked_attempt["finished_at"]
        or _assessment_identity(checked_assessment) != _attempt_source_identity(checked_attempt)
    ):
        raise CorruptData("Prerequisite assessment identity does not match its attempt.")

    path = store.file_path(topic_id, prerequisite_filename(file_id))
    with _file_lock(store, topic_id, file_id):
        current = validate_prerequisite_state(
            read_json(path, empty_prerequisite_state(topic_id, file_id)),
            topic_id=topic_id,
            file_id=file_id,
        )
        updated = _transition(current, checked_attempt, checked_assessment)
        if updated != current:
            write_json(path, updated)
        return copy.deepcopy(updated)


def current_assessment(
    state: dict[str, Any],
    *,
    map_revision: str,
    section_id: str,
    cv_id: str,
    cv_text_sha256: str,
) -> dict[str, Any] | None:
    """Return the newest completed result only when every selected source identity matches."""
    checked = validate_prerequisite_state(state, topic_id=state.get("topic_id", ""), file_id=state.get("file_id", ""))
    for assessment in reversed(checked["assessments"]):
        if (
            assessment["map_revision"] == map_revision
            and assessment["section_id"] == section_id
            and assessment["cv_id"] == cv_id
            and assessment["cv_text_sha256"] == cv_text_sha256
        ):
            return copy.deepcopy(assessment)
    return None


def recover_interrupted_attempts(
    store: Store,
    topic_id: str,
    file_id: str,
    *,
    active_attempt_ids: set[str],
    finished_at: str,
) -> bool:
    """Mark persisted generating attempts interrupted unless their IDs are live in this process."""
    _require_ready_file(store, topic_id, file_id)
    topic_id = valid_id(topic_id)
    file_id = valid_id(file_id)
    _validate_timestamp(finished_at)
    if not isinstance(active_attempt_ids, set) or not all(isinstance(item, str) for item in active_attempt_ids):
        raise CorruptData("Active prerequisite attempt identities are malformed.")
    path = store.file_path(topic_id, prerequisite_filename(file_id))
    with _file_lock(store, topic_id, file_id):
        state = validate_prerequisite_state(
            read_json(path, empty_prerequisite_state(topic_id, file_id)),
            topic_id=topic_id,
            file_id=file_id,
        )
        attempts = [
            {
                **attempt,
                "status": "interrupted",
                "finished_at": finished_at,
                "diagnostic": "Generation ended before completion. Retry the prerequisite assessment.",
            }
            if attempt["status"] == "generating" and attempt["id"] not in active_attempt_ids
            else attempt
            for attempt in state["attempts"]
        ]
        if attempts == state["attempts"]:
            return False
        state = {**state, "attempts": attempts}
        state = validate_prerequisite_state(state, topic_id=topic_id, file_id=file_id)
        write_json(path, state)
        return True


def _transition(state: dict[str, Any], attempt: dict[str, Any], assessment: dict[str, Any] | None) -> dict[str, Any]:
    attempts = list(state["attempts"])
    existing_index = next((index for index, item in enumerate(attempts) if item["id"] == attempt["id"]), None)
    if existing_index is None:
        if attempt["status"] != "generating":
            raise Conflict("A prerequisite attempt must be recorded as generating before it finishes.")
        if any(
            item["status"] == "generating" and item["assessment_id"] == attempt["assessment_id"] for item in attempts
        ):
            raise Conflict("This prerequisite assessment already has an active attempt.")
        if any(item["assessment_id"] == attempt["assessment_id"] for item in state["assessments"]):
            raise Conflict(
                "This prerequisite assessment is already complete and cannot be regenerated with the same ID."
            )
        attempts.append(attempt)
    else:
        previous = attempts[existing_index]
        if previous == attempt:
            if assessment is None:
                return state
            existing_result = next(
                (item for item in state["assessments"] if item["assessment_id"] == assessment["assessment_id"]),
                None,
            )
            if existing_result == assessment:
                return state
            raise Conflict("This prerequisite attempt already has a different completed result.")
        if previous["status"] != "generating" or attempt["status"] == "generating":
            raise Conflict("A finished prerequisite attempt is immutable.")
        if _attempt_identity(previous) != _attempt_identity(attempt):
            raise Conflict("A prerequisite attempt cannot change its source identity.")
        attempts[existing_index] = attempt

    assessments = list(state["assessments"])
    if assessment is not None:
        prior = next((item for item in assessments if item["assessment_id"] == assessment["assessment_id"]), None)
        if prior is not None:
            if prior == assessment:
                return state
            raise Conflict("A completed prerequisite assessment is immutable.")
        assessments.append(assessment)
    updated = {**state, "attempts": attempts, "assessments": assessments}
    return validate_prerequisite_state(updated, topic_id=state["topic_id"], file_id=state["file_id"])


def _validate_attempt(value: object, topic_id: str, file_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ATTEMPT_FIELDS:
        raise CorruptData("Prerequisite attempt is malformed or contains unsupported data.")
    if (
        not isinstance(value["id"], str)
        or not value["id"]
        or len(value["id"]) > 100
        or not isinstance(value["assessment_id"], str)
        or not value["assessment_id"]
        or len(value["assessment_id"]) > 100
        or value["topic_id"] != topic_id
        or value["file_id"] != file_id
        or not isinstance(value["map_revision"], str)
        or not _SHA256.fullmatch(value["map_revision"])
        or not isinstance(value["section_id"], str)
        or not valid_id(value["section_id"])
        or len(value["section_id"]) > 100
        or not isinstance(value["status"], str)
        or value["status"] not in _ATTEMPT_STATUSES
        or not isinstance(value["provenance"], dict)
        or set(value["provenance"]) != _PROVENANCE_FIELDS
        or not isinstance(value["diagnostic"], (str, type(None)))
        or (isinstance(value["diagnostic"], str) and len(value["diagnostic"]) > 2000)
    ):
        raise CorruptData("Prerequisite attempt has invalid identity, status or provenance.")
    _validate_timestamp(value["started_at"])
    if value["status"] == "generating":
        if value["finished_at"] is not None:
            raise CorruptData("Generating prerequisite attempts cannot have a finish time.")
        if value["diagnostic"] is not None:
            raise CorruptData("Generating prerequisite attempts cannot contain partial model output.")
    else:
        _validate_timestamp(value["finished_at"])
    provenance = value["provenance"]
    if (
        not isinstance(provenance["prompt_version"], str)
        or not provenance["prompt_version"]
        or not _is_sha256(provenance["source_sha256"])
        or not _is_sha256(provenance["runtime_policy_sha256"])
        or not isinstance(provenance["cv_id"], str)
        or not _CV_ID.fullmatch(provenance["cv_id"])
        or not _is_sha256(provenance["cv_text_sha256"])
        or not isinstance(provenance["goal"], str)
        or not isinstance(provenance["model"], str)
        or not provenance["model"]
    ):
        raise CorruptData("Prerequisite attempt provenance is malformed.")
    return copy.deepcopy(value)


def _validate_assessment(value: object, topic_id: str, file_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ASSESSMENT_FIELDS:
        raise CorruptData("Prerequisite assessment is malformed or contains unsupported data.")
    if (
        value["topic_id"] != topic_id
        or value["file_id"] != file_id
        or not isinstance(value["attempt_id"], str)
        or not value["attempt_id"]
        or not isinstance(value["assessment_id"], str)
        or not value["assessment_id"]
        or not isinstance(value["map_revision"], str)
        or not _SHA256.fullmatch(value["map_revision"])
        or not isinstance(value["section_id"], str)
        or not valid_id(value["section_id"])
        or not isinstance(value["cv_id"], str)
        or not _CV_ID.fullmatch(value["cv_id"])
        or not isinstance(value["cv_text_sha256"], str)
        or not _SHA256.fullmatch(value["cv_text_sha256"])
        or not isinstance(value["source_sha256"], str)
        or not _SHA256.fullmatch(value["source_sha256"])
        or not isinstance(value["overview"], str)
        or not value["overview"].strip()
        or len(value["overview"]) > 1200
        or not isinstance(value["requirements"], list)
        or len(value["requirements"]) > 8
        or not isinstance(value["sources"], list)
        or not value["sources"]
    ):
        raise CorruptData("Prerequisite assessment identity or content is invalid.")
    _validate_timestamp(value["finished_at"])
    source_labels = _validate_sources(value["sources"])
    _validate_requirements(value["requirements"], source_labels, value["assessment_id"])
    return copy.deepcopy(value)


def _validate_sources(sources: list[object]) -> set[str]:
    labels: set[str] = set()
    refs: set[str] = set()
    for source in sources:
        if (
            not isinstance(source, dict)
            or set(source) != _SOURCE_FIELDS
            or not isinstance(source["label"], str)
            or source["label"] != f"S{len(labels) + 1}"
            or not isinstance(source["unit_id"], str)
            or not source["unit_id"]
            or not isinstance(source["source_refs"], list)
            or not source["source_refs"]
            or not all(isinstance(ref, str) and ref for ref in source["source_refs"])
            or len(source["source_refs"]) != len(set(source["source_refs"]))
            or not isinstance(source["pages"], list)
            or not all(type(page) is int and page > 0 for page in source["pages"])
        ):
            raise CorruptData("Prerequisite assessment has invalid source metadata.")
        if refs.intersection(source["source_refs"]):
            raise CorruptData("Prerequisite assessment repeats a source reference.")
        labels.add(source["label"])
        refs.update(source["source_refs"])
    return labels


def _validate_requirements(requirements: list[object], source_labels: set[str], assessment_id: str) -> None:
    seen_ids: set[str] = set()
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict) or set(requirement) != _REQUIREMENT_FIELDS:
            raise CorruptData("Prerequisite requirement is malformed or contains unsupported data.")
        expected_id = "req-" + hashlib.sha256(f"{assessment_id}:{index}".encode("utf-8")).hexdigest()[:24]
        concept = requirement["concept"]
        if (
            not isinstance(requirement["requirement_id"], str)
            or not _REQUIREMENT_ID.fullmatch(requirement["requirement_id"])
            or requirement["requirement_id"] != expected_id
            or requirement["requirement_id"] in seen_ids
            or not isinstance(concept, str)
            or not concept.strip()
            or len(concept) > 160
            or not isinstance(requirement["reason"], str)
            or not requirement["reason"].strip()
            or len(requirement["reason"]) > 800
            or requirement["question"] != f"Are you already comfortable with {concept}?"
            or not isinstance(requirement["source_labels"], list)
            or not requirement["source_labels"]
            or not all(isinstance(label, str) for label in requirement["source_labels"])
            or not all(label in source_labels for label in requirement["source_labels"])
            or len(requirement["source_labels"]) != len(set(requirement["source_labels"]))
            or not isinstance(requirement["cv_background"], str)
            or requirement["cv_background"] not in {"mentioned", "not_stated"}
            or requirement["comfort"] is not None
            or requirement["comfort_status"] != "pending"
            or not isinstance(requirement["cv_quote"], str)
            or len(requirement["cv_quote"]) > 1000
        ):
            raise CorruptData("Prerequisite requirement identity, question, evidence or pending answer is invalid.")
        if requirement["cv_background"] == "not_stated":
            if requirement["cv_source_labels"] != [] or requirement["cv_quote"] != "":
                raise CorruptData("Unstated CV background cannot carry CV citations or a quote.")
        elif requirement["cv_source_labels"] != ["CV1"] or not requirement["cv_quote"].strip():
            raise CorruptData("Mentioned CV background requires its validated CV quote.")
        seen_ids.add(requirement["requirement_id"])


def _attempt_identity(attempt: dict[str, Any]) -> tuple[object, ...]:
    provenance = attempt["provenance"]
    return (
        attempt["id"],
        attempt["assessment_id"],
        attempt["topic_id"],
        attempt["file_id"],
        attempt["map_revision"],
        attempt["section_id"],
        attempt["started_at"],
        provenance["prompt_version"],
        provenance["goal"],
        provenance["model"],
        provenance["runtime_policy_sha256"],
        _attempt_source_identity(attempt),
    )


def _attempt_source_identity(attempt: dict[str, Any]) -> tuple[object, ...]:
    provenance = attempt["provenance"]
    return (
        attempt["assessment_id"],
        attempt["topic_id"],
        attempt["file_id"],
        attempt["map_revision"],
        attempt["section_id"],
        provenance["cv_id"],
        provenance["cv_text_sha256"],
        provenance["source_sha256"],
    )


def _assessment_identity(assessment: dict[str, Any]) -> tuple[object, ...]:
    return (
        assessment["assessment_id"],
        assessment["topic_id"],
        assessment["file_id"],
        assessment["map_revision"],
        assessment["section_id"],
        assessment["cv_id"],
        assessment["cv_text_sha256"],
        assessment["source_sha256"],
    )


def _require_ready_file(store: Store, topic_id: str, file_id: str) -> None:
    record = store.file(topic_id, file_id)
    if record.get("status") != "ready":
        raise Conflict("Prerequisites can only be saved for a ready attachment.")


@contextmanager
def _file_lock(store: Store, topic_id: str, file_id: str) -> Iterator[None]:
    lock_path = checked(store.file_path(topic_id, f".{valid_id(file_id)}.prerequisites.lock"))
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise Conflict("Prerequisite storage is unavailable or unsafe.") from exc
    with os.fdopen(descriptor, "rb") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _validate_timestamp(value: object) -> None:
    if not isinstance(value, str) or not value or len(value) > 100:
        raise CorruptData("Prerequisite attempt timestamp is malformed.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise CorruptData("Prerequisite attempt timestamp is malformed.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CorruptData("Prerequisite timestamps must include a timezone.")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None
