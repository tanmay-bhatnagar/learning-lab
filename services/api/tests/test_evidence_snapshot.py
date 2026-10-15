"""Production-boundary contracts for on-demand evidence prompt snapshots."""

from __future__ import annotations

import hashlib

import pytest

from lab.conversation_profile import save_conversation_profile
from lab.errors import Conflict, InvalidInput
from lab.evidence_snapshot import (
    bind_retained_sources,
    capture_prompt_context,
    revalidate_evidence_snapshot,
)
from lab.index import TopicIndex
from lab.profile_store import ProfileStore
from lab.storage import Store, write_json, write_text


@pytest.fixture
def snapshot_workspace(tmp_path):
    store = Store(tmp_path / "topics", tmp_path / "settings.json")
    topic = store.create("Synthetic evidence snapshot")
    topic_path = store.topic(topic["id"])
    write_json(
        topic_path / "topic.json",
        {"id": topic["id"], "name": topic["name"], "learning_goal": "Understand synthetic methods."},
    )
    write_json(
        topic_path / "files.json",
        [
            {"id": "paper", "name": "Paper.pdf", "status": "ready", "index_status": "ready"},
            {
                "id": "notes",
                "name": "Notes.md",
                "status": "ready",
                "index_status": "unindexed",
                "markdown_name": "notes.md",
            },
        ],
    )
    write_text(store.file_path(topic["id"], "notes.md"), "Synthetic unindexed notes.\n")
    chunk = {
        "chunk_id": "paper-chunk-1",
        "file_id": "paper",
        "file_name": "Paper.pdf",
        "chunk_index": 0,
        "text": "Synthetic indexed passage.",
        "content_hash": hashlib.sha256(b"Synthetic indexed passage.").hexdigest(),
        "headings": ["Methods"],
        "pages": [3],
        "bboxes": [{"page": 3, "l": 0.1, "t": 0.2, "r": 0.8, "b": 0.9, "coord_origin": "TOPLEFT"}],
        "asset_ids": ["figure-1"],
    }
    with TopicIndex(topic_path / "retrieval.sqlite") as index:
        index.replace_file("paper", [chunk])
    profile_store = ProfileStore(tmp_path / "profile")
    policy = tmp_path / "AGENTS.md"
    policy.write_text("Synthetic runtime policy.\n", encoding="utf-8")
    return {
        "store": store,
        "topic_id": topic["id"],
        "topic_path": topic_path,
        "profile_store": profile_store,
        "policy": policy,
        "chunk": chunk,
    }


def _capture(workspace, selected_file_ids=("paper", "notes")):
    return capture_prompt_context(
        store=workspace["store"],
        profile_store=workspace["profile_store"],
        topic_id=workspace["topic_id"],
        conversation_id="default",
        selected_file_ids=frozenset(selected_file_ids),
        runtime_policy_path=workspace["policy"],
    )


def _revalidate(workspace, snapshot):
    return revalidate_evidence_snapshot(
        snapshot,
        store=workspace["store"],
        profile_store=workspace["profile_store"],
        runtime_policy_path=workspace["policy"],
    )


def test_capture_keeps_ephemeral_text_out_of_immutable_snapshot(snapshot_workspace):
    captured = _capture(snapshot_workspace)

    assert captured.prompt_context["runtime_policy"] == "Synthetic runtime policy.\n"
    assert captured.prompt_context["learning_goal"] == "Understand synthetic methods."
    assert captured.prompt_context["attachments"]["notes"] == "Synthetic unindexed notes.\n"
    assert "Synthetic runtime policy" not in repr(captured.snapshot)
    assert "Synthetic unindexed notes" not in repr(captured.snapshot)
    assert captured.snapshot.include_cv is False
    assert captured.snapshot.selected_file_ids == frozenset({"paper", "notes"})


def test_cv_off_capture_and_revalidation_never_read_cv_registry_or_artifacts(snapshot_workspace, monkeypatch):
    profile_store = snapshot_workspace["profile_store"]

    def forbidden(*_args, **_kwargs):
        pytest.fail("CV-off evidence snapshots must not read CV registry or artifacts")

    monkeypatch.setattr(profile_store, "read_profile", forbidden)
    monkeypatch.setattr(profile_store, "read_extracted_text", forbidden)
    monkeypatch.setattr(profile_store, "read_active_cv_text", forbidden)

    captured = _capture(snapshot_workspace)
    _revalidate(snapshot_workspace, captured.snapshot)


def test_cv_off_to_on_preference_change_conflicts_before_any_cv_read(snapshot_workspace, monkeypatch):
    captured = _capture(snapshot_workspace)
    profile_store = snapshot_workspace["profile_store"]

    def forbidden(*_args, **_kwargs):
        pytest.fail("An off-to-on stale snapshot must stop before CV registry or artifact reads")

    monkeypatch.setattr(profile_store, "read_profile", forbidden)
    monkeypatch.setattr(profile_store, "read_extracted_text", forbidden)
    save_conversation_profile(
        snapshot_workspace["store"],
        snapshot_workspace["topic_id"],
        "default",
        updates={"include_cv": True},
        expected_revision=0,
    )

    with pytest.raises(Conflict):
        _revalidate(snapshot_workspace, captured.snapshot)


def test_bound_indexed_and_unindexed_sources_revalidate_the_actual_supplied_content(snapshot_workspace):
    captured = _capture(snapshot_workspace)
    bound = bind_retained_sources(
        captured.snapshot,
        [snapshot_workspace["chunk"]],
    )
    assert len(bound.supplied_sources) == 1

    _revalidate(snapshot_workspace, bound)

    with TopicIndex(snapshot_workspace["topic_path"] / "retrieval.sqlite") as index:
        changed = {**snapshot_workspace["chunk"], "text": "Changed indexed passage."}
        changed["content_hash"] = hashlib.sha256(changed["text"].encode()).hexdigest()
        index.replace_file("paper", [changed])

    with pytest.raises(Conflict):
        _revalidate(snapshot_workspace, bound)


def test_retained_sources_accumulate_and_same_id_cannot_change_projection(snapshot_workspace):
    captured = _capture(snapshot_workspace)
    first = bind_retained_sources(captured.snapshot, [snapshot_workspace["chunk"]])
    later_source = {
        **snapshot_workspace["chunk"],
        "chunk_id": "paper-chunk-2",
        "chunk_index": 1,
        "text": "Synthetic follow-up passage.",
        "content_hash": hashlib.sha256(b"Synthetic follow-up passage.").hexdigest(),
    }
    both = bind_retained_sources(first, [later_source])

    assert {item.chunk_id for item in both.supplied_sources} == {"paper-chunk-1", "paper-chunk-2"}
    changed_identity = {**snapshot_workspace["chunk"], "pages": [99]}
    with pytest.raises(InvalidInput):
        bind_retained_sources(both, [changed_identity])


def test_empty_manifest_does_not_query_unfiltered_index(snapshot_workspace, monkeypatch):
    captured = _capture(snapshot_workspace, selected_file_ids=("paper",))
    bound = bind_retained_sources(captured.snapshot, [])

    def forbidden(*_args, **_kwargs):
        pytest.fail("Empty retained-source manifests must not query the index")

    monkeypatch.setattr(TopicIndex, "get_chunks", forbidden)
    _revalidate(snapshot_workspace, bound)


def test_unindexed_markdown_bytes_are_rechecked(snapshot_workspace):
    captured = _capture(snapshot_workspace)

    write_text(snapshot_workspace["store"].file_path(snapshot_workspace["topic_id"], "notes.md"), "Changed notes.\n")

    with pytest.raises(Conflict):
        _revalidate(snapshot_workspace, captured.snapshot)
