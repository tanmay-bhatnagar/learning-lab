from __future__ import annotations

import copy
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

import pytest

from lab.conversation_profile import (
    DEFAULT_CONVERSATION_PROFILE,
    get_conversation_profile,
    save_conversation_profile,
)
from lab.errors import Conflict, CorruptData, InvalidInput, NotFound
from lab.storage import Store, read_bytes, write_json


def _store(tmp_path):
    store = Store(tmp_path / "Learning", tmp_path / "settings.json")
    topic = store.create("Synthetic conversation preferences")
    return store, topic["id"]


def _focus():
    return {
        "file_id": "synthetic-paper",
        "assessment_id": "assessment-1",
        "map_revision": "a" * 64,
        "section_id": "section-1",
        "goal": "Understand this synthetic section",
    }


def _save_from_process(root, settings, topic, conversation_id, include_cv):
    store = Store(root, settings)
    try:
        return save_conversation_profile(
            store,
            topic,
            conversation_id,
            updates={"include_cv": include_cv},
            expected_revision=0,
        )
    except Conflict:
        return "conflict"


def test_missing_preferences_default_without_rewriting_saved_session(tmp_path):
    store, topic = _store(tmp_path)
    session_path = store.file_path(topic, "session.json")
    write_json(session_path, {"messages": [{"role": "user", "content": "synthetic history"}]})
    original_session = read_bytes(session_path)

    state = get_conversation_profile(store, topic, "default")

    assert state == DEFAULT_CONVERSATION_PROFILE
    assert read_bytes(session_path) == original_session
    assert not store.file_path(topic, "conversation_profile_default.json").exists()


def test_preferences_are_isolated_by_topic_and_existing_conversation(tmp_path):
    store, topic = _store(tmp_path)
    second_topic = store.create("Another synthetic topic")["id"]
    conversation = store.create_conversation(topic, "Synthetic chat")
    session_path = store.file_path(topic, f"conversation_{conversation['id']}.json")
    original_session = read_bytes(session_path)
    updates = {"include_cv": True}

    saved = save_conversation_profile(
        store,
        topic,
        conversation["id"],
        updates=updates,
        expected_revision=0,
    )

    assert saved == {"schema_version": 1, "revision": 1, "include_cv": True, "active_assessment": None}
    assert updates == {"include_cv": True}
    assert read_bytes(session_path) == original_session
    assert get_conversation_profile(store, second_topic, "default") == DEFAULT_CONVERSATION_PROFILE
    with pytest.raises(NotFound):
        get_conversation_profile(store, topic, "missing-chat")
    with pytest.raises(NotFound):
        save_conversation_profile(store, topic, "missing-chat", updates=updates, expected_revision=0)


def test_cv_toggle_and_active_focus_preserve_the_other_value(tmp_path):
    store, topic = _store(tmp_path)
    conversation = store.create_conversation(topic, "Independent preferences")
    conversation_id = conversation["id"]

    cv_enabled = save_conversation_profile(
        store, topic, conversation_id, updates={"include_cv": True}, expected_revision=0
    )
    focused = save_conversation_profile(
        store,
        topic,
        conversation_id,
        updates={"active_assessment": _focus()},
        expected_revision=1,
    )
    cv_disabled = save_conversation_profile(
        store, topic, conversation_id, updates={"include_cv": False}, expected_revision=2
    )

    assert cv_enabled["active_assessment"] is None
    assert focused["include_cv"] is True
    assert focused["active_assessment"] == _focus()
    assert cv_disabled["include_cv"] is False
    assert cv_disabled["active_assessment"] == _focus()
    assert [cv_enabled["revision"], focused["revision"], cv_disabled["revision"]] == [1, 2, 3]


def test_stale_expected_revision_leaves_saved_preferences_unchanged(tmp_path):
    store, topic = _store(tmp_path)
    conversation = store.create_conversation(topic, "Revision conflict")
    conversation_id = conversation["id"]
    saved = save_conversation_profile(store, topic, conversation_id, updates={"include_cv": True}, expected_revision=0)
    original = copy.deepcopy(saved)

    with pytest.raises(Conflict):
        save_conversation_profile(
            store,
            topic,
            conversation_id,
            updates={"active_assessment": _focus()},
            expected_revision=0,
        )

    assert get_conversation_profile(store, topic, conversation_id) == original


def test_two_processes_writing_the_same_revision_cannot_both_succeed(tmp_path):
    store, topic = _store(tmp_path)
    conversation = store.create_conversation(topic, "Concurrent updates")
    conversation_id = conversation["id"]

    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(
            pool.map(
                _save_from_process,
                [store.root, store.root],
                [store.settings, store.settings],
                [topic, topic],
                [conversation_id, conversation_id],
                [True, False],
            )
        )

    assert sum(result != "conflict" for result in results) == 1
    assert sum(result == "conflict" for result in results) == 1
    assert get_conversation_profile(store, topic, conversation_id)["revision"] == 1


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": 2, "revision": 0, "include_cv": False, "active_assessment": None},
        {"schema_version": 1, "revision": True, "include_cv": False, "active_assessment": None},
        {"schema_version": 1, "revision": 0, "include_cv": 0, "active_assessment": None},
        {
            "schema_version": 1,
            "revision": 0,
            "include_cv": False,
            "active_assessment": {**_focus(), "cv_text": "must not be persisted"},
        },
    ],
)
def test_corrupt_or_unknown_preference_schema_fails_visibly(tmp_path, value):
    store, topic = _store(tmp_path)
    write_json(store.file_path(topic, "conversation_profile_default.json"), value)

    with pytest.raises(CorruptData):
        get_conversation_profile(store, topic, "default")


def test_invalid_updates_and_invalid_active_focus_are_rejected_without_writes(tmp_path):
    store, topic = _store(tmp_path)
    conversation = store.create_conversation(topic, "Reject invalid state")
    conversation_id = conversation["id"]
    invalid_updates = [
        {"include_cv": 1},
        {"include_cv": "true"},
        {"unexpected": True},
        {},
        {"active_assessment": {**_focus(), "file_id": "../outside"}},
        {"active_assessment": {**_focus(), "map_revision": "not-a-revision"}},
    ]

    for updates in invalid_updates:
        with pytest.raises(InvalidInput):
            save_conversation_profile(
                store,
                topic,
                conversation_id,
                updates=updates,
                expected_revision=0,
            )
        assert get_conversation_profile(store, topic, conversation_id) == DEFAULT_CONVERSATION_PROFILE
