"""Pure learner-profile filename rules and profile-store persistence tests."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from lab.errors import Conflict, CorruptData, Forbidden, InvalidInput
from lab.learner_profile import (
    add_manual_proficiency,
    empty_proficiency,
    filename_collision_key,
    proficiency_context,
    update_manual_proficiency,
    validate_cv_filename,
)
from lab.profile_store import ProfileStore


def _register_same_name(root, filename, content, barrier, results):
    barrier.wait()
    try:
        record = ProfileStore(root).register_cv(filename, content, content.decode(), {"status": "ready"})
        results.put(("ready", record["id"]))
    except Conflict:
        results.put(("conflict", None))


@pytest.mark.parametrize("filename", ["CV 2026.pdf", "Mañana résumé.pdf", "报告.pdf"])
def test_cv_filename_preserves_user_selected_basename(filename):
    assert validate_cv_filename(filename) == filename


@pytest.mark.parametrize("filename", ["", ".", "..", "../cv.pdf", "dir/cv.pdf", "dir\\cv.pdf", "cv\n.pdf"])
def test_cv_filename_rejects_unsafe_names(filename):
    with pytest.raises(InvalidInput):
        validate_cv_filename(filename)


def test_filename_collision_key_uses_unicode_normalization_and_casefold():
    assert filename_collision_key("Résumé.PDF") == filename_collision_key("Re\u0301sume\u0301.pdf")
    assert filename_collision_key("Résumé.PDF") == filename_collision_key("résumé.pdf")


def test_registration_preserves_original_and_blocks_duplicate_name(tmp_path):
    store = ProfileStore(tmp_path)
    original = b"synthetic CV original bytes"

    record = store.register_cv("CV 2026.pdf", original, "Synthetic extracted text", {"status": "ready"})

    assert record["status"] == "ready"
    assert (tmp_path / "CVs" / "CV 2026.pdf").read_bytes() == original
    with pytest.raises(Conflict):
        store.register_cv("cv 2026.PDF", b"replacement", "different text", {"status": "ready"})
    assert (tmp_path / "CVs" / "CV 2026.pdf").read_bytes() == original


def test_failed_extraction_keeps_original_but_is_not_eligible(tmp_path):
    store = ProfileStore(tmp_path)
    original = b"synthetic PDF bytes"

    record = store.register_cv("Unreadable CV.pdf", original, "", {"status": "error", "findings": ["empty"]})

    assert record["status"] == "error"
    assert record["id"] != store.read_profile()["active_cv_id"]
    assert (tmp_path / "CVs" / "Unreadable CV.pdf").read_bytes() == original


def test_empty_text_cannot_be_marked_ready(tmp_path):
    store = ProfileStore(tmp_path)

    record = store.register_cv("Empty CV.pdf", b"synthetic original", " \n\t", {"status": "ready"})

    assert record["status"] == "error"
    assert record["extracted_sha256"] is None
    with pytest.raises(Conflict):
        store.select_cv(record["id"], expected_revision=store.read_profile()["revision"])


def test_select_and_revoke_use_expected_revision_and_clear_active_selection(tmp_path):
    store = ProfileStore(tmp_path)
    first = store.register_cv("First.pdf", b"one", "One", {"status": "ready"})
    second = store.register_cv("Second.pdf", b"two", "Two", {"status": "ready"})
    state = store.read_profile()

    selected = store.select_cv(second["id"], expected_revision=state["revision"])
    revoked = store.revoke_cv(second["id"], expected_revision=selected["revision"])

    assert revoked["active_cv_id"] is None
    assert first["id"] in {item["id"] for item in revoked["cvs"]}
    with pytest.raises(Conflict):
        store.select_cv(second["id"], expected_revision=revoked["revision"])


def test_extracted_text_is_preserved_byte_for_byte_and_revocation_blocks_read(tmp_path):
    text = "Résumé\n  exact spacing\tand punctuation: α, β.\n"
    store = ProfileStore(tmp_path)
    record = store.register_cv("Text CV.pdf", b"synthetic original", text, {"status": "ready"})
    profile = store.read_profile()
    selected = store.select_cv(record["id"], expected_revision=profile["revision"])

    assert store.read_extracted_text(record["id"]).encode("utf-8") == text.encode("utf-8")
    revoked = store.revoke_cv(record["id"], expected_revision=selected["revision"])
    assert revoked["active_cv_id"] is None
    with pytest.raises(Conflict):
        store.read_extracted_text(record["id"])


def test_stale_profile_revision_is_rejected(tmp_path):
    store = ProfileStore(tmp_path)
    record = store.register_cv("Current.pdf", b"original", "Full text", {"status": "ready"})
    current = store.read_profile()
    store.select_cv(record["id"], expected_revision=current["revision"])

    with pytest.raises(Conflict):
        store.revoke_cv(record["id"], expected_revision=current["revision"])


def test_corrupt_or_unsupported_profile_blocks_read_and_registration(tmp_path):
    store = ProfileStore(tmp_path)
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / "profile.json").write_text('{"schema_version":99}', encoding="utf-8")

    with pytest.raises(CorruptData):
        store.read_profile()
    with pytest.raises(CorruptData):
        store.register_cv("New.pdf", b"new original", "text", {"status": "ready"})


def test_tampered_extraction_is_blocked_instead_of_returned_as_eligible(tmp_path):
    store = ProfileStore(tmp_path)
    record = store.register_cv("Integrity.pdf", b"synthetic original", "Complete CV text", {"status": "ready"})
    profile = store.read_profile()
    selected = store.select_cv(record["id"], expected_revision=profile["revision"])
    extraction = tmp_path / "CVs" / ".records" / record["id"] / "extracted.txt"
    extraction.write_text("partial/tampered", encoding="utf-8")

    with pytest.raises(CorruptData):
        store.read_extracted_text(selected["active_cv_id"])


def test_symlink_profile_storage_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "Profile"
    root.mkdir()
    (root / "CVs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(Forbidden):
        ProfileStore(root)


def test_failed_registration_with_orphan_original_does_not_overwrite_on_retry(tmp_path, monkeypatch):
    import lab.profile_store as profile_store_module

    store = ProfileStore(tmp_path)
    original = b"first original"
    write = profile_store_module.write_json

    def fail_profile_write(path, data):
        if Path(path).name == "profile.json":
            raise OSError("synthetic metadata write failure")
        write(path, data)

    monkeypatch.setattr(profile_store_module, "write_json", fail_profile_write)
    with pytest.raises(OSError):
        store.register_cv(".write-Orphan.pdf", original, "text", {"status": "ready"})
    monkeypatch.setattr(profile_store_module, "write_json", write)

    with pytest.raises(Conflict):
        store.register_cv(".write-Orphan.pdf", b"replacement", "new text", {"status": "ready"})
    assert (tmp_path / "CVs" / ".write-Orphan.pdf").read_bytes() == original


def test_exclusive_original_publish_race_becomes_domain_conflict(tmp_path, monkeypatch):
    import lab.profile_store as profile_store_module
    from lab.storage import write_new_bytes as atomic_write_new_bytes

    store = ProfileStore(tmp_path)

    def create_racing_original(path, data):
        if Path(path).name == "Race.pdf":
            Path(path).write_bytes(b"winner")
        atomic_write_new_bytes(path, data)

    monkeypatch.setattr(profile_store_module, "write_new_bytes", create_racing_original)
    with pytest.raises(Conflict):
        store.register_cv("Race.pdf", b"loser", "text", {"status": "ready"})
    assert (tmp_path / "CVs" / "Race.pdf").read_bytes() == b"winner"


def test_concurrent_processes_cannot_register_normalized_name_collision(tmp_path):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(target=_register_same_name, args=(str(tmp_path), filename, content, barrier, results))
        for filename, content in (("Résumé.pdf", b"first"), ("Re\u0301sume\u0301.PDF", b"second"))
    ]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        assert process.exitcode == 0

    assert sorted(outcome for outcome, _ in outcomes) == ["conflict", "ready"]
    stored = next(path.read_bytes() for path in (tmp_path / "CVs").iterdir() if path.name != ".records")
    assert stored in {b"first", b"second"}


def test_proficiency_projection_is_compact_scoped_and_does_not_mutate_state():
    original = empty_proficiency()
    state = add_manual_proficiency(
        original,
        concept="Python basics",
        comfort="refresher",
        notes="Some experience",
        expected_revision=0,
        entry_id="3" * 32,
        updated_at="2026-10-12T00:00:00+00:00",
    )
    with_requirement = {
        **state,
        "entries": [
            *state["entries"],
            {
                "id": "a" * 32,
                "concept": "Probability",
                "comfort": None,
                "notes": "",
                "source_kind": "model_requirement",
                "topic_id": "topic-one",
                "assessment_id": "assessment-one",
                "requirement_id": "requirement-one",
            },
        ],
    }

    projection = proficiency_context(
        with_requirement,
        topic_id="topic-one",
        active_assessment_id="assessment-one",
    )

    assert projection == (
        "My proficiency (self-reported):\n- Python basics: refresher — Some experience\n- Probability: pending"
    )
    assert "topic-one" not in projection
    assert with_requirement["entries"][1]["comfort"] is None
    assert original == empty_proficiency()


def test_add_manual_proficiency_uses_explicit_identity_and_timestamp():
    state = empty_proficiency()

    inputs = {
        "concept": "Python",
        "comfort": "new",
        "notes": "",
        "expected_revision": 0,
        "entry_id": "1" * 32,
        "updated_at": "2026-10-12T00:00:00+00:00",
    }
    updated = add_manual_proficiency(
        state,
        **inputs,
    )
    repeated = add_manual_proficiency(state, **inputs)

    assert updated["entries"][0]["id"] == "1" * 32
    assert updated["entries"][0]["updated_at"] == "2026-10-12T00:00:00+00:00"
    assert repeated == updated
    assert state == empty_proficiency()


def test_update_manual_proficiency_uses_explicit_timestamp():
    state = {
        **empty_proficiency(),
        "revision": 1,
        "entries": [
            {
                "id": "2" * 32,
                "concept": "Python",
                "comfort": "new",
                "notes": "",
                "source_kind": "user_manual",
                "updated_at": "2026-10-11T00:00:00+00:00",
            }
        ],
    }

    inputs = {
        "updates": {"comfort": "comfortable"},
        "expected_revision": 1,
        "updated_at": "2026-10-12T00:00:00+00:00",
    }
    updated = update_manual_proficiency(
        state,
        "2" * 32,
        **inputs,
    )
    repeated = update_manual_proficiency(state, "2" * 32, **inputs)

    assert updated["entries"][0]["comfort"] == "comfortable"
    assert updated["entries"][0]["updated_at"] == "2026-10-12T00:00:00+00:00"
    assert repeated == updated
    assert state["entries"][0]["comfort"] == "new"


def _active_cv(store, filename="Selected CV.pdf", text="Synthetic CV evidence"):
    record = store.register_cv(filename, filename.encode(), text, {"status": "ready"})
    profile = store.read_profile()
    selected = store.select_cv(record["id"], expected_revision=profile["revision"])
    return selected["cvs"][0]


def _model_requirements(assessment_id="assessment-one"):
    import hashlib

    return [
        {
            "requirement_id": "req-" + hashlib.sha256(f"{assessment_id}:0".encode()).hexdigest()[:24],
            "concept": "Python fundamentals",
        },
        {
            "requirement_id": "req-" + hashlib.sha256(f"{assessment_id}:1".encode()).hexdigest()[:24],
            "concept": "Probability",
        },
    ]


def test_server_registers_each_requirement_as_pending_without_copying_manual_comfort(tmp_path):
    store = ProfileStore(tmp_path)
    selected_cv = _active_cv(store)
    manual = store.add_proficiency(
        concept="Python fundamentals",
        comfort="comfortable",
        notes="Self-reported, never inferred from my CV",
        expected_revision=0,
    )

    registered = store.register_model_requirements(
        _model_requirements(),
        topic_id="topic-one",
        assessment_id="assessment-one",
        selected_cv_id=selected_cv["id"],
        selected_cv_text_sha256=selected_cv["extracted_sha256"],
    )

    model_rows = [entry for entry in registered["entries"] if entry["source_kind"] == "model_requirement"]
    assert len(model_rows) == 2
    assert [(item["requirement_id"], item["concept"]) for item in model_rows] == [
        (requirement["requirement_id"], requirement["concept"]) for requirement in _model_requirements()
    ]
    assert all(item["comfort"] is None and item["notes"] == "" for item in model_rows)
    assert all(item["topic_id"] == "topic-one" and item["assessment_id"] == "assessment-one" for item in model_rows)
    assert registered["entries"][0]["id"] == manual["entries"][0]["id"]
    assert registered["entries"][0]["comfort"] == "comfortable"
    assert registered["entries"][0]["notes"] == "Self-reported, never inferred from my CV"


def test_requirement_registration_is_idempotent_and_never_resets_answer_or_notes(tmp_path):
    store = ProfileStore(tmp_path)
    selected_cv = _active_cv(store)
    requirements = _model_requirements()
    registered = store.register_model_requirements(
        requirements,
        topic_id="topic-one",
        assessment_id="assessment-one",
        selected_cv_id=selected_cv["id"],
        selected_cv_text_sha256=selected_cv["extracted_sha256"],
    )
    first = next(item for item in registered["entries"] if item["source_kind"] == "model_requirement")
    answered = store.save_proficiency_batch(
        additions=[],
        updates=[{"id": first["id"], "comfort": "refresher", "notes": "Review examples"}],
        expected_revision=registered["revision"],
    )

    repeated = store.register_model_requirements(
        requirements,
        topic_id="topic-one",
        assessment_id="assessment-one",
        selected_cv_id=selected_cv["id"],
        selected_cv_text_sha256=selected_cv["extracted_sha256"],
    )

    assert repeated == answered
    assert len([item for item in repeated["entries"] if item["source_kind"] == "model_requirement"]) == 2
    saved = next(item for item in repeated["entries"] if item["id"] == first["id"])
    assert (saved["comfort"], saved["notes"]) == ("refresher", "Review examples")


def test_zero_requirements_do_not_change_proficiency_revision(tmp_path):
    store = ProfileStore(tmp_path)
    selected_cv = _active_cv(store)
    before = store.read_proficiency()

    after = store.register_model_requirements(
        [],
        topic_id="topic-one",
        assessment_id="assessment-empty",
        selected_cv_id=selected_cv["id"],
        selected_cv_text_sha256=selected_cv["extracted_sha256"],
    )

    assert after == before


def test_requirement_registration_refuses_changed_active_cv_without_writing(tmp_path):
    store = ProfileStore(tmp_path)
    previous_cv = _active_cv(store, "First CV.pdf", "First CV text")
    next_cv = store.register_cv("Second CV.pdf", b"second", "Second CV text", {"status": "ready"})
    profile = store.read_profile()
    store.select_cv(next_cv["id"], expected_revision=profile["revision"])
    before = store.read_proficiency()

    with pytest.raises(Conflict):
        store.register_model_requirements(
            _model_requirements(),
            topic_id="topic-one",
            assessment_id="assessment-one",
            selected_cv_id=previous_cv["id"],
            selected_cv_text_sha256=previous_cv["extracted_sha256"],
        )

    assert store.read_proficiency() == before


def test_requirement_registration_capacity_failure_does_not_write(tmp_path):
    from lab.learner_profile import MAX_PROFICIENCY_ENTRIES, PROFICIENCY_VERSION
    from lab.storage import write_json

    store = ProfileStore(tmp_path)
    selected_cv = _active_cv(store)
    entries = [
        {
            "id": f"{index:032x}",
            "concept": f"Existing concept {index}",
            "comfort": "unsure",
            "notes": "",
            "source_kind": "user_manual",
            "updated_at": "2026-10-13T00:00:00+00:00",
        }
        for index in range(MAX_PROFICIENCY_ENTRIES - 1)
    ]
    write_json(store.proficiency_path, {"schema_version": PROFICIENCY_VERSION, "revision": 4, "entries": entries})
    before = store.read_proficiency()

    with pytest.raises(InvalidInput):
        store.register_model_requirements(
            _model_requirements(),
            topic_id="topic-one",
            assessment_id="assessment-one",
            selected_cv_id=selected_cv["id"],
            selected_cv_text_sha256=selected_cv["extracted_sha256"],
        )

    assert store.read_proficiency() == before


def test_requirement_registration_rejects_duplicate_requirement_ids(tmp_path):
    store = ProfileStore(tmp_path)
    selected_cv = _active_cv(store)
    repeated = _model_requirements()[0]

    with pytest.raises(InvalidInput):
        store.register_model_requirements(
            [repeated, repeated],
            topic_id="topic-one",
            assessment_id="assessment-one",
            selected_cv_id=selected_cv["id"],
            selected_cv_text_sha256=selected_cv["extracted_sha256"],
        )

    assert store.read_proficiency()["entries"] == []


def test_same_registration_identity_cannot_change_requirement_concept(tmp_path):
    store = ProfileStore(tmp_path)
    selected_cv = _active_cv(store)
    requirement = _model_requirements()[0]
    store.register_model_requirements(
        [requirement],
        topic_id="topic-one",
        assessment_id="assessment-one",
        selected_cv_id=selected_cv["id"],
        selected_cv_text_sha256=selected_cv["extracted_sha256"],
    )
    before = store.read_proficiency()

    with pytest.raises(Conflict):
        store.register_model_requirements(
            [{**requirement, "concept": "Different concept"}],
            topic_id="topic-one",
            assessment_id="assessment-one",
            selected_cv_id=selected_cv["id"],
            selected_cv_text_sha256=selected_cv["extracted_sha256"],
        )

    assert store.read_proficiency() == before
