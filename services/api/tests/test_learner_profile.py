"""Pure learner-profile filename rules and profile-store persistence tests."""

from __future__ import annotations

import pytest

from lab.errors import Conflict, InvalidInput
from lab.learner_profile import filename_collision_key, validate_cv_filename
from lab.profile_store import ProfileStore


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


def test_select_and_revoke_use_expected_revision_and_clear_active_selection(tmp_path):
    store = ProfileStore(tmp_path)
    first = store.register_cv("First.pdf", b"one", "One", {"status": "ready"})
    second = store.register_cv("Second.pdf", b"two", "Two", {"status": "ready"})
    state = store.read_profile()

    selected = store.select_cv(second["id"], expected_revision=state["revision"])
    revoked = store.revoke_cv(second["id"], expected_revision=selected["revision"])

    assert revoked["active_cv_id"] is None
    assert first["id"] in {item["id"] for item in revoked["cvs"]}
