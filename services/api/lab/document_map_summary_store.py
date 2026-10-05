"""Atomic state transitions for per-section summary attempts and saved results."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from .document_map_store import _current_revision, _read_saved_map, _source_record, _validated_map, map_filename
from .errors import Conflict, CorruptData, NotFound
from .section_summary import SavedSummary, SummaryAttempt
from .storage import Store, write_json

AttemptStatus = Literal["generating", "completed", "cancelled", "error", "interrupted"]


def write_summary_attempt(
    store: Store,
    topic: str,
    file_id: str,
    attempt: dict[str, object],
    *,
    summary: dict[str, object] | None = None,
) -> dict[str, object]:
    """Atomically publish one attempt transition and an optional completed summary."""
    try:
        checked_attempt = SummaryAttempt.model_validate(attempt)
    except ValidationError as exc:
        raise CorruptData("Section-summary attempt is malformed.") from exc
    path = store.file_path(topic, map_filename(file_id))
    record = _read_saved_map(store, topic, file_id)
    if record is None:
        raise Conflict("Build the document map before generating a section summary.")
    _, source_revision = _source_record(store, topic, file_id)
    revision = _current_revision(file_id, source_revision)
    if record["revision"] != revision or checked_attempt.revision != revision:
        raise Conflict("This document map is out of date. Rebuild it before generating a summary.")
    section = _find_section(record["sections"], checked_attempt.section_id)
    if section is None:
        raise NotFound("Section is not present in the current document map.")
    existing = section.get("latest_attempt")
    if existing and existing.get("id") != checked_attempt.id and existing.get("status") == "generating":
        raise Conflict("A section summary is already generating; wait for it to finish.")
    if existing and existing.get("id") == checked_attempt.id and existing.get("status") != "generating":
        raise Conflict("This section-summary attempt has already finished.")
    if checked_attempt.status == "generating" and checked_attempt.finished_at is not None:
        raise CorruptData("A generating section-summary attempt cannot have a finish time.")
    if checked_attempt.status != "generating" and checked_attempt.finished_at is None:
        raise CorruptData("A finished section-summary attempt must have a finish time.")
    section["latest_attempt"] = checked_attempt.model_dump(mode="json")
    if summary is not None:
        try:
            checked_summary = SavedSummary.model_validate(summary)
        except ValidationError as exc:
            raise CorruptData("Completed section summary is malformed.") from exc
        if checked_attempt.status != "completed" or checked_summary.id != checked_attempt.id:
            raise CorruptData("Only a completed attempt can publish its matching saved summary.")
        section["last_summary"] = checked_summary.model_dump(mode="json")
    validated = _validated_map(record, expected_file_id=file_id)
    write_json(path, validated)
    return section["latest_attempt"]


def recover_interrupted_attempts(
    store: Store,
    topic: str,
    file_id: str,
    *,
    active_attempt_ids: set[str],
    finished_at: str,
) -> bool:
    """Mark persisted attempts interrupted only when their exact attempt is not live in this process."""
    record = _read_saved_map(store, topic, file_id)
    if record is None:
        return False
    changed = False

    def visit(sections: list[dict[str, object]]) -> None:
        nonlocal changed
        for section in sections:
            attempt = section.get("latest_attempt")
            if (
                isinstance(attempt, dict)
                and attempt.get("status") == "generating"
                and attempt.get("id") not in active_attempt_ids
            ):
                section["latest_attempt"] = {
                    **attempt,
                    "status": "interrupted",
                    "finished_at": finished_at,
                    "error": "Generation ended before completion. Retry the summary.",
                }
                changed = True
            visit(section["children"])

    visit(record["sections"])
    for snapshot in record["history"]:
        visit(snapshot["sections"])
    if changed:
        validated = _validated_map(record, expected_file_id=file_id)
        write_json(store.file_path(topic, map_filename(file_id)), validated)
    return changed


def _find_section(sections: list[dict[str, object]], section_id: str) -> dict[str, object] | None:
    for section in sections:
        if section["id"] == section_id:
            return section
        found = _find_section(section["children"], section_id)
        if found is not None:
            return found
    return None
