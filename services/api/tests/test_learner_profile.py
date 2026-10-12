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
        "My proficiency (self-reported):\n"
        "- Python basics: refresher — Some experience\n"
        "- Probability: pending"
    )
    assert "topic-one" not in projection
    assert with_requirement["entries"][1]["comfort"] is None
    assert original == empty_proficiency()
