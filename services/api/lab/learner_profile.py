"""Pure validation and transitions for versioned learner CV profile state."""

from __future__ import annotations

import copy
import re
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from lab.errors import Conflict, CorruptData, InvalidInput, NotFound

PROFILE_VERSION = 1
PROFICIENCY_VERSION = 1
MAX_PROFICIENCY_ENTRIES = 50
Comfort = Literal["comfortable", "refresher", "new", "unsure"]
_CV_ID = re.compile(r"^[a-f0-9]{32}$")
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def validate_cv_filename(filename: str) -> str:
    """Validate a user-selected portable basename without renaming it."""
    invalid = (
        not isinstance(filename, str)
        or not filename
        or filename in {".", ".."}
        or filename != filename.strip()
        or any(char in filename for char in '/\\<>:\x00"|?*')
        or any(ord(char) < 32 for char in filename)
        or filename.endswith(".")
    )
    if invalid:
        raise InvalidInput("Choose a valid filename without folders, control characters or reserved symbols.")
    if filename.split(".", 1)[0].casefold() in _WINDOWS_RESERVED:
        raise InvalidInput("Choose a filename that is not reserved by the operating system.")
    return filename


def filename_collision_key(filename: str) -> str:
    """Return a portable collision key while leaving the displayed name unchanged."""
    return unicodedata.normalize("NFC", validate_cv_filename(filename)).casefold()


def empty_profile() -> dict[str, Any]:
    return {"schema_version": PROFILE_VERSION, "revision": 0, "active_cv_id": None, "cvs": []}


def validate_profile(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != PROFILE_VERSION:
        raise CorruptData("Unsupported or invalid learner profile; restore a compatible profile backup.")
    revision = value.get("revision")
    active_cv_id = value.get("active_cv_id")
    cvs = value.get("cvs")
    if type(revision) is not int or revision < 0 or not isinstance(cvs, list):
        raise CorruptData("Invalid learner profile; restore a compatible profile backup.")
    if active_cv_id is not None and (not isinstance(active_cv_id, str) or not _CV_ID.fullmatch(active_cv_id)):
        raise CorruptData("Invalid learner profile selection; restore a compatible profile backup.")
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for candidate in cvs:
        if not isinstance(candidate, dict):
            raise CorruptData("Invalid CV record in learner profile; restore a compatible profile backup.")
        record = copy.deepcopy(candidate)
        cv_id = record.get("id")
        original_name = record.get("original_name")
        status = record.get("status")
        revoked = record.get("revoked")
        if (
            not isinstance(cv_id, str)
            or not _CV_ID.fullmatch(cv_id)
            or cv_id in seen_ids
            or not isinstance(original_name, str)
            or status not in {"ready", "error"}
            or type(revoked) is not bool
        ):
            raise CorruptData("Invalid CV record in learner profile; restore a compatible profile backup.")
        try:
            key = filename_collision_key(original_name)
        except InvalidInput:
            raise CorruptData("Invalid CV filename in learner profile; restore a compatible profile backup.") from None
        if key in seen_names:
            raise CorruptData("Duplicate CV filename in learner profile; restore a compatible profile backup.")
        if status == "ready" and not isinstance(record.get("extracted_sha256"), str):
            raise CorruptData("Ready CV record has no extracted-text identity; restore a compatible backup.")
        if status == "error" and record.get("extracted_sha256") is not None:
            raise CorruptData("Failed CV record cannot be eligible; restore a compatible backup.")
        seen_ids.add(cv_id)
        seen_names.add(key)
        normalized.append(record)
    if active_cv_id is not None:
        active = next((record for record in normalized if record["id"] == active_cv_id), None)
        if active is None or active["status"] != "ready" or active["revoked"]:
            raise CorruptData("Selected CV is missing, failed or revoked; restore a compatible profile backup.")
    return {"schema_version": PROFILE_VERSION, "revision": revision, "active_cv_id": active_cv_id, "cvs": normalized}


def add_cv_record(profile: dict[str, Any], record: dict[str, Any], expected_revision: int) -> dict[str, Any]:
    current = validate_profile(profile)
    _require_revision(current, expected_revision)
    if record["id"] in {item["id"] for item in current["cvs"]}:
        raise Conflict("This CV version is already registered.")
    key = filename_collision_key(record["original_name"])
    if key in {filename_collision_key(item["original_name"]) for item in current["cvs"]}:
        raise Conflict("A CV with the same filename is already registered.")
    updated = {**current, "revision": current["revision"] + 1, "cvs": [*current["cvs"], copy.deepcopy(record)]}
    return validate_profile(updated)


def select_cv_record(profile: dict[str, Any], cv_id: str, expected_revision: int) -> dict[str, Any]:
    current = validate_profile(profile)
    _require_revision(current, expected_revision)
    record = next((item for item in current["cvs"] if item["id"] == cv_id), None)
    if record is None or record["status"] != "ready" or record["revoked"]:
        raise Conflict("Only an available, successfully extracted CV can be selected.")
    return validate_profile({**current, "revision": current["revision"] + 1, "active_cv_id": cv_id})


def revoke_cv_record(profile: dict[str, Any], cv_id: str, expected_revision: int) -> dict[str, Any]:
    current = validate_profile(profile)
    _require_revision(current, expected_revision)
    if not any(item["id"] == cv_id for item in current["cvs"]):
        raise Conflict("CV version is not registered.")
    cvs = [{**record, "revoked": True} if record["id"] == cv_id else record for record in current["cvs"]]
    active_cv_id = None if current["active_cv_id"] == cv_id else current["active_cv_id"]
    return validate_profile({**current, "revision": current["revision"] + 1, "active_cv_id": active_cv_id, "cvs": cvs})


def _require_revision(profile: dict[str, Any], expected_revision: int) -> None:
    if type(expected_revision) is not int or expected_revision != profile["revision"]:
        raise Conflict("Learner profile changed; reload it before saving this update.")


def empty_proficiency() -> dict[str, Any]:
    return {"schema_version": PROFICIENCY_VERSION, "revision": 0, "entries": []}


def validate_proficiency(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != PROFICIENCY_VERSION:
        raise CorruptData("Unsupported or invalid My proficiency data; restore a compatible backup.")
    revision = value.get("revision")
    entries = value.get("entries")
    if type(revision) is not int or revision < 0 or not isinstance(entries, list):
        raise CorruptData("Invalid My proficiency data; restore a compatible backup.")
    if len(entries) > MAX_PROFICIENCY_ENTRIES:
        raise CorruptData("My proficiency exceeds its supported entry limit; restore a compatible backup.")
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    manual_labels: set[str] = set()
    for candidate in entries:
        if not isinstance(candidate, dict):
            raise CorruptData("Invalid proficiency entry; restore a compatible backup.")
        entry = copy.deepcopy(candidate)
        entry_id = entry.get("id")
        concept = entry.get("concept")
        comfort = entry.get("comfort")
        notes = entry.get("notes", "")
        source_kind = entry.get("source_kind")
        if (
            not isinstance(entry_id, str)
            or not _CV_ID.fullmatch(entry_id)
            or entry_id in ids
            or not isinstance(concept, str)
            or not isinstance(notes, str)
            or source_kind not in {"user_manual", "model_requirement"}
        ):
            raise CorruptData("Invalid proficiency entry; restore a compatible backup.")
        try:
            clean_concept = _clean_concept(concept)
            clean_notes = _clean_notes(notes)
        except InvalidInput:
            raise CorruptData("Invalid proficiency entry text; restore a compatible backup.") from None
        if source_kind == "user_manual":
            if comfort not in {"comfortable", "refresher", "new", "unsure"}:
                raise CorruptData("Invalid manual proficiency level; restore a compatible backup.")
            if any(key in entry for key in ("topic_id", "assessment_id", "requirement_id")):
                raise CorruptData("Manual proficiency cannot carry model assessment identity.")
            label = proficiency_label_key(clean_concept)
            if label in manual_labels:
                raise CorruptData("Duplicate manual proficiency concept; restore a compatible backup.")
            manual_labels.add(label)
        else:
            if (
                comfort not in {None, "comfortable", "refresher", "new", "unsure"}
                or not all(isinstance(entry.get(key), str) and entry[key] for key in ("topic_id", "assessment_id", "requirement_id"))
            ):
                raise CorruptData("Invalid model requirement provenance; restore a compatible backup.")
        if clean_concept != concept or clean_notes != notes:
            raise CorruptData("Proficiency entry is not in canonical form; restore a compatible backup.")
        ids.add(entry_id)
        normalized.append(entry)
    return {"schema_version": PROFICIENCY_VERSION, "revision": revision, "entries": normalized}


def add_manual_proficiency(
    state: dict[str, Any],
    *,
    concept: str,
    comfort: Comfort,
    notes: str,
    expected_revision: int,
) -> dict[str, Any]:
    current = validate_proficiency(state)
    _require_revision(current, expected_revision)
    if len(current["entries"]) >= MAX_PROFICIENCY_ENTRIES:
        raise InvalidInput(f"My proficiency supports up to {MAX_PROFICIENCY_ENTRIES} entries.")
    clean_concept = _clean_concept(concept)
    clean_notes = _clean_notes(notes)
    if comfort not in {"comfortable", "refresher", "new", "unsure"}:
        raise InvalidInput("Choose Comfortable, Needs a refresher, New to me, or Not sure.")
    label = proficiency_label_key(clean_concept)
    if any(
        entry["source_kind"] == "user_manual" and proficiency_label_key(entry["concept"]) == label
        for entry in current["entries"]
    ):
        raise Conflict("This concept is already in My proficiency.")
    entry = {
        "id": uuid.uuid4().hex,
        "concept": clean_concept,
        "comfort": comfort,
        "notes": clean_notes,
        "source_kind": "user_manual",
        "updated_at": datetime.now(UTC).isoformat(),
    }
    return validate_proficiency(
        {**current, "revision": current["revision"] + 1, "entries": [*current["entries"], entry]}
    )


def update_manual_proficiency(
    state: dict[str, Any],
    entry_id: str,
    *,
    updates: dict[str, Any],
    expected_revision: int,
) -> dict[str, Any]:
    current = validate_proficiency(state)
    _require_revision(current, expected_revision)
    if not updates or set(updates) - {"concept", "comfort", "notes"}:
        raise InvalidInput("Update at least one concept, proficiency or note field.")
    selected = next((entry for entry in current["entries"] if entry["id"] == entry_id), None)
    if selected is None or selected["source_kind"] != "user_manual":
        raise NotFound("Manual proficiency entry not found.")
    changed = {**selected, **updates}
    changed["concept"] = _clean_concept(changed["concept"])
    changed["notes"] = _clean_notes(changed.get("notes", ""))
    if changed["comfort"] not in {"comfortable", "refresher", "new", "unsure"}:
        raise InvalidInput("Choose Comfortable, Needs a refresher, New to me, or Not sure.")
    key = proficiency_label_key(changed["concept"])
    if any(
        entry["id"] != entry_id
        and entry["source_kind"] == "user_manual"
        and proficiency_label_key(entry["concept"]) == key
        for entry in current["entries"]
    ):
        raise Conflict("This concept is already in My proficiency.")
    changed["updated_at"] = datetime.now(UTC).isoformat()
    entries = [changed if entry["id"] == entry_id else entry for entry in current["entries"]]
    return validate_proficiency({**current, "revision": current["revision"] + 1, "entries": entries})


def proficiency_context(
    state: dict[str, Any], *, topic_id: str | None = None, active_assessment_id: str | None = None
) -> str:
    """Format a compact current self-report; never serialize storage metadata into chat."""
    current = validate_proficiency(state)
    if not current["entries"]:
        return ""
    lines = ["My proficiency (self-reported):"]
    for entry in current["entries"]:
        if entry["source_kind"] == "user_manual":
            line = f"- {entry['concept']}: {entry['comfort']}"
            if entry["notes"]:
                line += f" — {entry['notes']}"
            lines.append(line)
        elif (
            topic_id is not None
            and active_assessment_id is not None
            and entry["topic_id"] == topic_id
            and entry["assessment_id"] == active_assessment_id
        ):
            response = entry["comfort"] or "pending"
            lines.append(f"- {entry['concept']}: {response}")
    return "\n".join(lines)


def proficiency_label_key(concept: str) -> str:
    return " ".join(unicodedata.normalize("NFC", _clean_concept(concept)).casefold().split())


def _clean_concept(concept: str) -> str:
    if not isinstance(concept, str):
        raise InvalidInput("Concept must be text.")
    value = concept.strip()
    if not value or len(value) > 160 or any(ord(char) < 32 for char in value):
        raise InvalidInput("Concept must contain 1–160 printable characters.")
    return value


def _clean_notes(notes: str) -> str:
    if not isinstance(notes, str):
        raise InvalidInput("Proficiency notes must be text.")
    value = notes.strip()
    if len(value) > 240 or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise InvalidInput("Proficiency notes must be at most 240 printable characters.")
    return value
