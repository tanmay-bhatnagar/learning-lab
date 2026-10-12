"""Atomic I/O boundary for reusable CV originals and extracted text."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from lab.errors import Conflict, CorruptData, Forbidden, InvalidInput, NotFound
from lab.learner_profile import (
    add_cv_record,
    empty_profile,
    filename_collision_key,
    revoke_cv_record,
    select_cv_record,
    validate_cv_filename,
    validate_profile,
)
from lab.storage import checked, read_bytes, read_json, write_json, write_new_bytes

_PROFILE_FILENAME = "profile.json"
_LOCK_FILENAME = ".profile.lock"


class ProfileStore:
    """Store originals by their user-selected filename under a shared profile root."""

    def __init__(self, root: Path | str) -> None:
        self.root = checked(root).resolve()
        self.cv_root = checked(self.root / "CVs")
        self.profile_path = checked(self.root / _PROFILE_FILENAME)
        self.lock_path = checked(self.root / _LOCK_FILENAME)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        checked(self.root)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise Forbidden("Learner profile storage is unavailable or unsafe.") from exc
        with os.fdopen(fd, "rb") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def read_profile(self) -> dict[str, Any]:
        with self._locked():
            return self._read_unlocked()

    def register_cv(
        self,
        original_name: str,
        original_bytes: bytes,
        extracted_text: str,
        extraction_diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        filename = validate_cv_filename(original_name)
        if not isinstance(original_bytes, bytes) or not original_bytes:
            raise InvalidInput("The uploaded CV must contain non-empty original bytes.")
        if not isinstance(extracted_text, str) or not isinstance(extraction_diagnostics, dict):
            raise InvalidInput("CV extraction data is invalid.")
        diagnostics = copy.deepcopy(extraction_diagnostics)
        try:
            json.dumps(diagnostics, ensure_ascii=False)
        except (TypeError, ValueError):
            raise InvalidInput("CV extraction diagnostics must contain JSON-compatible values.") from None
        ready = diagnostics.get("status") == "ready" and bool(extracted_text.strip())
        if diagnostics.get("status") == "ready" and not extracted_text.strip():
            diagnostics = {
                **diagnostics,
                "status": "error",
                "findings": [*diagnostics.get("findings", []), "No extracted CV text is available."],
            }
        cv_id = uuid.uuid4().hex
        record = {
            "id": cv_id,
            "original_name": filename,
            "status": "ready" if ready else "error",
            "revoked": False,
            "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "extracted_sha256": hashlib.sha256(extracted_text.encode("utf-8")).hexdigest() if ready else None,
            "extraction_diagnostics": diagnostics,
            "created_at": datetime.now(UTC).isoformat(),
        }
        with self._locked():
            profile = self._read_unlocked()
            self.cv_root.mkdir(parents=True, exist_ok=True)
            self._reject_filename_collision(filename)
            original_path = checked(self.cv_root / filename)
            write_new_bytes(original_path, original_bytes)
            if ready:
                record_dir = checked(self.cv_root / ".records" / cv_id)
                record_dir.mkdir(parents=True, exist_ok=False)
                write_new_bytes(checked(record_dir / "extracted.txt"), extracted_text.encode("utf-8"))
            updated = add_cv_record(profile, record, profile["revision"])
            write_json(self.profile_path, updated)
            return copy.deepcopy(record)

    def read_extracted_text(self, cv_id: str) -> str:
        with self._locked():
            profile = self._read_unlocked()
            if profile["active_cv_id"] != cv_id:
                raise Conflict("Select an available CV before using its extracted text.")
            record = self._find_record(profile, cv_id)
            if record["status"] != "ready" or record["revoked"]:
                raise Conflict("Only the selected, successfully extracted CV can be used.")
            path = self._text_path(cv_id)
            try:
                data = read_bytes(path)
            except NotFound:
                raise CorruptData("Selected CV text is missing; restore a compatible profile backup.") from None
            if hashlib.sha256(data).hexdigest() != record["extracted_sha256"]:
                raise CorruptData("Selected CV text failed its integrity check; restore a compatible backup.")
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                raise CorruptData("Selected CV text is not valid UTF-8; restore a compatible backup.") from None

    def select_cv(self, cv_id: str, expected_revision: int) -> dict[str, Any]:
        with self._locked():
            profile = self._read_unlocked()
            updated = select_cv_record(profile, cv_id, expected_revision)
            write_json(self.profile_path, updated)
            return copy.deepcopy(updated)

    def revoke_cv(self, cv_id: str, expected_revision: int) -> dict[str, Any]:
        with self._locked():
            profile = self._read_unlocked()
            updated = revoke_cv_record(profile, cv_id, expected_revision)
            write_json(self.profile_path, updated)
            return copy.deepcopy(updated)

    def _read_unlocked(self) -> dict[str, Any]:
        raw = read_json(self.profile_path, empty_profile())
        profile = validate_profile(raw)
        for record in profile["cvs"]:
            original_path = checked(self.cv_root / record["original_name"])
            try:
                original = read_bytes(original_path)
            except NotFound:
                raise CorruptData("A registered CV original is missing; restore a compatible profile backup.") from None
            if hashlib.sha256(original).hexdigest() != record.get("original_sha256"):
                raise CorruptData("A registered CV original failed its integrity check; restore a backup.")
            if record["status"] == "ready":
                try:
                    extracted = read_bytes(self._text_path(record["id"]))
                except NotFound:
                    raise CorruptData("A registered CV extraction is missing; restore a compatible backup.") from None
                if hashlib.sha256(extracted).hexdigest() != record["extracted_sha256"]:
                    raise CorruptData("A registered CV extraction failed its integrity check; restore a backup.")
                try:
                    extracted.decode("utf-8")
                except UnicodeDecodeError:
                    raise CorruptData("A registered CV extraction is not valid UTF-8; restore a backup.") from None
        return profile

    def _reject_filename_collision(self, filename: str) -> None:
        key = filename_collision_key(filename)
        for candidate in self.cv_root.iterdir():
            if candidate.name == ".records":
                continue
            if candidate.name.startswith(".write-"):
                continue
            try:
                candidate_key = filename_collision_key(candidate.name)
            except InvalidInput:
                continue
            if candidate_key == key:
                raise Conflict("A file with the same filename already exists. Choose a different name.")
        if self._profile_path_exists():
            profile = validate_profile(read_json(self.profile_path))
            if any(filename_collision_key(record["original_name"]) == key for record in profile["cvs"]):
                raise Conflict("A CV with the same filename is already registered.")

    def _profile_path_exists(self) -> bool:
        return self.profile_path.exists()

    def _text_path(self, cv_id: str) -> Path:
        if not isinstance(cv_id, str) or len(cv_id) != 32 or any(char not in "0123456789abcdef" for char in cv_id):
            raise InvalidInput("Invalid CV version ID.")
        return checked(self.cv_root / ".records" / cv_id / "extracted.txt")

    @staticmethod
    def _find_record(profile: dict[str, Any], cv_id: str) -> dict[str, Any]:
        record = next((item for item in profile["cvs"] if item["id"] == cv_id), None)
        if record is None:
            raise NotFound("CV version not found.")
        return record
