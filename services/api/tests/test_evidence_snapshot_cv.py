"""Real profile-store contracts for CV identity in evidence snapshots."""

from __future__ import annotations

import hashlib

import pytest

from lab.conversation_profile import save_conversation_profile
from lab.errors import Conflict, CorruptData
from lab.evidence_snapshot import capture_prompt_context, revalidate_evidence_snapshot
from lab.profile_store import ProfileStore
from lab.storage import Store


@pytest.fixture
def cv_snapshot_workspace(tmp_path):
    store = Store(tmp_path / "topics", tmp_path / "settings.json")
    topic = store.create("Synthetic CV snapshot")
    profile_store = ProfileStore(tmp_path / "profile")
    cv_text = "Synthetic complete CV text, identity marker CV-SNAPSHOT-916.\n"
    first = profile_store.register_cv(
        "First CV.pdf",
        b"synthetic first original",
        cv_text,
        {"status": "ready", "findings": []},
    )
    second = profile_store.register_cv(
        "Second CV.pdf",
        b"synthetic second original",
        cv_text,
        {"status": "ready", "findings": []},
    )
    profile_store.select_cv(first["id"], expected_revision=2)
    save_conversation_profile(
        store,
        topic["id"],
        "default",
        updates={"include_cv": True},
        expected_revision=0,
    )
    policy = tmp_path / "AGENTS.md"
    policy.write_text("Synthetic complete runtime policy.\n", encoding="utf-8")
    return {
        "store": store,
        "topic_id": topic["id"],
        "profile_store": profile_store,
        "first": first,
        "second": second,
        "cv_text": cv_text,
        "policy": policy,
    }


def _capture(workspace):
    return capture_prompt_context(
        store=workspace["store"],
        profile_store=workspace["profile_store"],
        topic_id=workspace["topic_id"],
        conversation_id="default",
        selected_file_ids=frozenset(),
        runtime_policy_path=workspace["policy"],
    )


def _revalidate(workspace, snapshot):
    return revalidate_evidence_snapshot(
        snapshot,
        store=workspace["store"],
        profile_store=workspace["profile_store"],
        runtime_policy_path=workspace["policy"],
    )


def test_cv_on_snapshot_keeps_literal_prompt_text_ephemeral_and_revalidates_stable_identity(cv_snapshot_workspace):
    workspace = cv_snapshot_workspace

    captured = _capture(workspace)

    assert captured.prompt_context["cv_text"] == workspace["cv_text"]
    assert captured.prompt_context["cv_name"] == "First CV.pdf"
    assert captured.snapshot.cv_id == workspace["first"]["id"]
    assert captured.snapshot.cv_name == "First CV.pdf"
    assert captured.snapshot.cv_text_sha256 == hashlib.sha256(workspace["cv_text"].encode()).hexdigest()
    assert workspace["cv_text"] not in repr(captured.snapshot)
    _revalidate(workspace, captured.snapshot)


def test_identical_text_from_a_different_active_cv_id_invalidates_snapshot(cv_snapshot_workspace):
    workspace = cv_snapshot_workspace
    captured = _capture(workspace)
    assert workspace["first"]["extracted_sha256"] == workspace["second"]["extracted_sha256"]

    workspace["profile_store"].select_cv(workspace["second"]["id"], expected_revision=3)

    with pytest.raises(Conflict):
        _revalidate(workspace, captured.snapshot)


def test_revoked_selected_cv_invalidates_snapshot(cv_snapshot_workspace):
    workspace = cv_snapshot_workspace
    captured = _capture(workspace)

    workspace["profile_store"].revoke_cv(workspace["first"]["id"], expected_revision=3)

    with pytest.raises(Conflict):
        _revalidate(workspace, captured.snapshot)


def test_changed_extracted_cv_bytes_fail_integrity_during_snapshot_revalidation(cv_snapshot_workspace):
    workspace = cv_snapshot_workspace
    captured = _capture(workspace)
    extracted_path = workspace["profile_store"]._text_path(workspace["first"]["id"])
    extracted_path.write_text("Changed synthetic CV text.\n", encoding="utf-8")

    with pytest.raises(CorruptData):
        _revalidate(workspace, captured.snapshot)


def test_cv_identity_change_during_text_load_aborts_capture(cv_snapshot_workspace, monkeypatch):
    workspace = cv_snapshot_workspace
    profile_store = workspace["profile_store"]
    read_extracted_text = profile_store.read_extracted_text

    def read_then_select_other(cv_id: str) -> str:
        text = read_extracted_text(cv_id)
        profile = profile_store.read_profile()
        profile_store.select_cv(workspace["second"]["id"], expected_revision=profile["revision"])
        return text

    monkeypatch.setattr(profile_store, "read_extracted_text", read_then_select_other)

    with pytest.raises(Conflict):
        _capture(workspace)


def test_unrelated_cv_registration_during_selected_text_read_does_not_conflict(cv_snapshot_workspace, monkeypatch):
    workspace = cv_snapshot_workspace
    profile_store = workspace["profile_store"]
    read_extracted_text = profile_store.read_extracted_text
    reads = 0

    def read_then_register_unrelated(cv_id):
        nonlocal reads
        text = read_extracted_text(cv_id)
        reads += 1
        if reads == 1:
            profile_store.register_cv(
                "Unrelated CV.pdf",
                b"synthetic unrelated original",
                "Unrelated synthetic CV text.",
                {"status": "ready", "findings": []},
            )
        return text

    monkeypatch.setattr(profile_store, "read_extracted_text", read_then_register_unrelated)

    captured = _capture(workspace)

    assert captured.snapshot.cv_id == workspace["first"]["id"]
    assert captured.prompt_context["cv_text"] == workspace["cv_text"]
    _revalidate(workspace, captured.snapshot)
