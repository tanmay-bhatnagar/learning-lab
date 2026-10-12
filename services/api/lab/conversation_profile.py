"""Versioned preferences for learner context in one existing conversation."""

from __future__ import annotations

import copy
import fcntl
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from lab.errors import Conflict, CorruptData, Forbidden, InvalidInput
from lab.storage import Store, checked, read_json, valid_id, write_json

CONVERSATION_PROFILE_VERSION = 1
_DEFAULT_CONVERSATION_PROFILE = {
    "schema_version": CONVERSATION_PROFILE_VERSION,
    "revision": 0,
    "include_cv": False,
    "active_assessment": None,
}
_LOCK_FILENAME = ".conversation-profile.lock"
_PREFERENCE_PREFIX = "learner_context_"
_MAP_REVISION = re.compile(r"^[a-f0-9]{64}$")
_ACTIVE_ASSESSMENT_FIELDS = {"file_id", "assessment_id", "map_revision", "section_id", "goal"}
_UPDATE_FIELDS = {"include_cv", "active_assessment"}


def empty_conversation_profile() -> dict[str, Any]:
    """Return a fresh version-1 default without changing saved conversation history."""
    return copy.deepcopy(_DEFAULT_CONVERSATION_PROFILE)


def validate_conversation_profile(value: object) -> dict[str, Any]:
    """Validate the exact stored preference schema and retain only safe focus metadata."""
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "revision", "include_cv", "active_assessment"}
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != CONVERSATION_PROFILE_VERSION
        or type(value.get("revision")) is not int
        or value["revision"] < 0
        or type(value.get("include_cv")) is not bool
    ):
        raise CorruptData("Saved conversation learner-context preferences are unsupported or malformed.")
    focus = value["active_assessment"]
    if focus is not None:
        if not isinstance(focus, dict) or set(focus) != _ACTIVE_ASSESSMENT_FIELDS:
            raise CorruptData("Saved conversation assessment focus is malformed.")
        if any(
            not isinstance(focus.get(field), str)
            or not focus[field]
            or len(focus[field]) > 2000
            or any(ord(char) < 32 for char in focus[field])
            for field in ("file_id", "assessment_id", "section_id")
        ):
            raise CorruptData("Saved conversation assessment source identity is malformed.")
        try:
            for field in ("file_id", "assessment_id", "section_id"):
                valid_id(focus[field])
        except InvalidInput as exc:
            raise CorruptData("Saved conversation assessment source identity is malformed.") from exc
        if not isinstance(focus.get("map_revision"), str) or not _MAP_REVISION.fullmatch(focus["map_revision"]):
            raise CorruptData("Saved conversation assessment map revision is malformed.")
        if not isinstance(focus.get("goal"), str) or len(focus["goal"]) > 2000:
            raise CorruptData("Saved conversation assessment goal is malformed.")
        if any(ord(char) < 32 and char not in "\n\t\r" for char in focus["goal"]):
            raise CorruptData("Saved conversation assessment goal is malformed.")
        focus = copy.deepcopy(focus)
    return {
        "schema_version": CONVERSATION_PROFILE_VERSION,
        "revision": value["revision"],
        "include_cv": value["include_cv"],
        "active_assessment": focus,
    }


def update_conversation_profile(
    current: object,
    *,
    updates: dict[str, object],
    expected_revision: int,
) -> dict[str, Any]:
    """Apply a strict partial preference update with optimistic revision checking."""
    state = validate_conversation_profile(current)
    if type(expected_revision) is not int or expected_revision < 0:
        raise InvalidInput("expected_revision must be a nonnegative integer.")
    if expected_revision != state["revision"]:
        raise Conflict("Conversation preferences changed; reload and retry your update.")
    if not isinstance(updates, dict) or not updates or set(updates) - _UPDATE_FIELDS:
        raise InvalidInput("Update at least one supported conversation learner-context preference.")
    candidate = {**state, **copy.deepcopy(updates), "revision": state["revision"] + 1}
    try:
        return validate_conversation_profile(candidate)
    except CorruptData as exc:
        raise InvalidInput("Conversation learner-context preference update is invalid.") from exc


@contextmanager
def _locked_conversation(store: Store, topic_id: str, conversation_id: str) -> Iterator[None]:
    store.topic(topic_id)
    lock_path = store.file_path(topic_id, _LOCK_FILENAME)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise Forbidden("Conversation preference storage is unavailable or unsafe.") from exc
    with os.fdopen(descriptor, "rb") as lock_file:
        if not stat.S_ISREG(os.fstat(lock_file.fileno()).st_mode):
            raise Forbidden("Conversation preference lock must be a regular file.")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            store.conversation(topic_id, conversation_id)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _preference_path(store: Store, topic_id: str, conversation_id: str) -> Path:
    if not isinstance(conversation_id, str):
        raise InvalidInput("Invalid conversation ID.")
    valid_id(conversation_id)
    return store.file_path(topic_id, f"{_PREFERENCE_PREFIX}{conversation_id}.json")


def get_conversation_profile(store: Store, topic_id: str, conversation_id: str = "default") -> dict[str, Any]:
    """Read preferences for an existing conversation, defaulting without session migration."""
    with _locked_conversation(store, topic_id, conversation_id):
        state = read_json(_preference_path(store, topic_id, conversation_id), empty_conversation_profile())
        return validate_conversation_profile(state)


def save_conversation_profile(
    store: Store,
    topic_id: str,
    conversation_id: str,
    *,
    updates: dict[str, object],
    expected_revision: int,
) -> dict[str, Any]:
    """Atomically save preferences for an existing conversation under a cross-process lock."""
    with _locked_conversation(store, topic_id, conversation_id):
        path = _preference_path(store, topic_id, conversation_id)
        current = validate_conversation_profile(read_json(path, empty_conversation_profile()))
        updated = update_conversation_profile(current, updates=updates, expected_revision=expected_revision)
        write_json(path, updated)
        return copy.deepcopy(updated)
