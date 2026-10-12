"""Pure validation and transitions for versioned learner CV profile state."""

from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

from lab.errors import Conflict, CorruptData, InvalidInput

PROFILE_VERSION = 1
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
