from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest

from lab.evidence_prompt import (
    build_final_evidence_prompt,
    build_initial_evidence_prompt,
    prioritize_evidence_sources,
)
from lab.errors import InvalidInput


def _source(chunk_id: str, text: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "file_id": f"file-{chunk_id}",
        "file_name": f"{chunk_id}.pdf",
        "chunk_index": 0,
        "text": text,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "headings": [],
        "pages": [1],
        "bboxes": [],
        "asset_ids": [],
    }


def _citation(source: dict[str, object]) -> dict[str, object]:
    return {
        "chunk_id": source["chunk_id"],
        "file_id": source["file_id"],
        "file_name": source["file_name"],
        "headings": [],
        "pages": [1],
        "bboxes": [],
        "assets": [],
        "trace": {},
        "text": str(source["text"])[:80],
    }


def _prompt_kwargs(sources: list[dict[str, object]]) -> dict[str, object]:
    return {
        "history": [],
        "evidence": [{"role": "user", "content": f"Study passage: {source['text']}"} for source in sources],
        "citations": [_citation(source) for source in sources],
        "attachments": [],
        "question": "Compare the supplied findings.",
        "active_topic": "synthetic-topic",
        "learning_goal": "",
        "runtime_policy": "Synthetic policy for tests.",
        "context_limit": 8192,
        "retrieval_record": {},
    }


def _user_content(plan: dict[str, object]) -> str:
    return "\n".join(str(message["content"]) for message in plan["prompt"] if message["role"] == "user")


def test_initial_prompt_labels_full_hash_sources_and_returns_retained_manifest():
    first = _source("chunk-a", "Full indexed source text A. " * 100)
    second = _source("chunk-b", "Full indexed source text B. " * 100)
    kwargs = _prompt_kwargs([first, second])
    kwargs["context_limit"] = 16384
    original_kwargs = deepcopy(kwargs)
    original_sources = deepcopy([first, second])
    plan = build_initial_evidence_prompt(
        prompt_kwargs=kwargs,
        source_chunks=[first, second],
        selected_file_ids={"file-chunk-a", "file-chunk-b"},
    )

    manifest_by_id = {item.source_id: item for item in plan["source_manifest"]}
    citations_by_id = {item["chunk_id"]: item for item in plan["citations"]}

    assert set(manifest_by_id) == set(citations_by_id) == {"chunk-a", "chunk-b"}
    assert manifest_by_id["chunk-a"].content_sha256 == hashlib.sha256(first["text"].encode()).hexdigest()
    assert manifest_by_id["chunk-b"].content_sha256 == hashlib.sha256(second["text"].encode()).hexdigest()
    assert manifest_by_id["chunk-a"].label == citations_by_id["chunk-a"]["source_label"] == "E1"
    assert manifest_by_id["chunk-b"].label == citations_by_id["chunk-b"]["source_label"] == "E2"
    assert "[E1]" in _user_content(plan) and "[E2]" in _user_content(plan)
    assert "request one additional selected-document search" in plan["prompt"][0]["content"].casefold()
    assert kwargs == original_kwargs
    assert [first, second] == original_sources


def test_initial_prompt_defines_exact_exclusive_action_object_and_empty_branch_fields():
    source = _source("chunk-a", "Evidence from the selected paper.")
    kwargs = _prompt_kwargs([source])
    kwargs["context_limit"] = 16384
    plan = build_initial_evidence_prompt(
        prompt_kwargs=kwargs,
        source_chunks=[source],
        selected_file_ids={"file-chunk-a"},
    )
    instruction = str(plan["prompt"][0]["content"]).casefold()

    assert "return exactly one json action object" in instruction
    assert "fields action, answer, source_labels, query" in instruction
    assert '{"action":"answer"' in instruction
    assert '"source_labels":["e1"]' in instruction
    assert '"query":""' in instruction
    assert '{"action":"search_selected","answer":"","source_labels":[]' in instruction
    assert '"query":"one search query"' in instruction
    assert "never return both" in instruction
    assert "do not copy or rephrase the user's question" in instruction
    assert "never request a file, path, topic, or conversation identifier" in instruction


def test_initial_manifest_uses_full_source_not_short_citation_excerpt():
    source = _source("chunk-full", "Complete indexed content. " * 40)
    kwargs = _prompt_kwargs([source])
    excerpt = str(source["text"])[:40]
    kwargs["citations"] = [{**_citation(source), "text": excerpt}]

    plan = build_initial_evidence_prompt(
        prompt_kwargs=kwargs,
        source_chunks=[source],
        selected_file_ids={"file-chunk-full"},
    )

    assert plan["source_manifest"][0].content_sha256 == source["content_hash"]
    assert plan["source_manifest"][0].content_sha256 != hashlib.sha256(excerpt.encode()).hexdigest()


def test_initial_manifest_contains_only_evidence_retained_by_context_budget():
    first = _source("chunk-small", "Small source B.")
    second = _source("chunk-large", "Large source A. " * 500)
    kwargs = _prompt_kwargs([first, second])
    kwargs["context_limit"] = 4096

    plan = build_initial_evidence_prompt(
        prompt_kwargs=kwargs,
        source_chunks=[first, second],
        selected_file_ids={"file-chunk-large", "file-chunk-small"},
    )

    retained_ids = {citation["chunk_id"] for citation in plan["citations"]}
    manifest_ids = {reference.source_id for reference in plan["source_manifest"]}
    assert retained_ids == manifest_ids
    assert len(manifest_ids) == 1
    retained = plan["source_manifest"][0]
    assert retained.source_id == "chunk-small"
    assert retained.label == "E1"


def test_initial_prompt_rejects_a_citation_without_a_full_matching_source():
    source = _source("chunk-a", "Full indexed source.")
    kwargs = _prompt_kwargs([source])
    kwargs["citations"] = [{**_citation(source), "chunk_id": "unknown-chunk"}]

    with pytest.raises(InvalidInput, match="source"):
        build_initial_evidence_prompt(
            prompt_kwargs=kwargs,
            source_chunks=[source],
            selected_file_ids={"file-chunk-a"},
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("file_id", "other-file"), ("file_name", "other.pdf"), ("pages", [2])],
)
def test_initial_prompt_rejects_citation_with_mismatched_source_panel_identity(field, value):
    source = _source("chunk-a", "Full indexed source.")
    kwargs = _prompt_kwargs([source])
    kwargs["citations"] = [{**_citation(source), field: value}]

    with pytest.raises(InvalidInput, match="source"):
        build_initial_evidence_prompt(
            prompt_kwargs=kwargs,
            source_chunks=[source],
            selected_file_ids={"file-chunk-a"},
        )


def test_initial_prompt_rejects_source_text_missing_from_matched_evidence_message():
    source = _source("chunk-a", "Full indexed text must be supplied to the model.")
    kwargs = _prompt_kwargs([source])
    kwargs["evidence"] = [{"role": "user", "content": "Only a short citation excerpt."}]

    with pytest.raises(InvalidInput, match="source text"):
        build_initial_evidence_prompt(
            prompt_kwargs=kwargs,
            source_chunks=[source],
            selected_file_ids={"file-chunk-a"},
        )


def test_initial_prompt_allows_empty_retained_manifest_with_selected_file_scope():
    kwargs = _prompt_kwargs([])

    plan = build_initial_evidence_prompt(
        prompt_kwargs=kwargs,
        source_chunks=[],
        selected_file_ids={"selected-indexed-file"},
    )

    assert plan["source_manifest"] == ()
    assert plan["citations"] == []


def test_final_prompt_balances_initial_and_additional_sources_and_forbids_more_search():
    initial = [_source(f"old-{index}", f"Initial evidence {index}.") for index in range(3)]
    additional = [_source(f"new-{index}", f"Additional evidence {index}.") for index in range(3)]
    selected_file_ids = {str(source["file_id"]) for source in [*initial, *additional]}
    prioritized = prioritize_evidence_sources(initial, additional, selected_file_ids=selected_file_ids, max_sources=4)

    plan = build_final_evidence_prompt(
        prompt_kwargs=_prompt_kwargs([*initial, *additional]),
        initial_chunks=initial,
        additional_chunks=additional,
        selected_file_ids=selected_file_ids,
        max_sources=4,
    )

    assert prioritized == ("new-0", "old-0", "new-1", "old-1")
    assert {item.source_id for item in plan["source_manifest"]} == set(prioritized)
    assert all(citation.get("source_label") for citation in plan["citations"])
    assert plan["retrieval_record"]["citations"] == plan["citations"]
    assert "Initial evidence 2." not in _user_content(plan)
    assert "Additional evidence 2." not in _user_content(plan)
    assert "Initial evidence 0." in _user_content(plan)
    assert "Additional evidence 0." in _user_content(plan)
    assert "do not request another search" in plan["prompt"][0]["content"].casefold()
    assert "request one additional selected-document search" not in plan["prompt"][0]["content"].casefold()
    assert "complete markdown answer" in plan["prompt"][0]["content"].casefold()
    assert "json action object" not in plan["prompt"][0]["content"].casefold()


def test_source_priority_preserves_rank_and_does_not_mutate_inputs():
    initial = [_source(f"old-{index}", f"Initial evidence {index}.") for index in range(3)]
    additional = [_source(f"new-{index}", f"Additional evidence {index}.") for index in range(3)]
    original_initial = [dict(source) for source in initial]
    original_additional = [dict(source) for source in additional]

    selected_file_ids = {str(source["file_id"]) for source in [*initial, *additional]}
    ordered_ids = prioritize_evidence_sources(initial, additional, selected_file_ids=selected_file_ids, max_sources=5)

    assert ordered_ids == ("new-0", "old-0", "new-1", "old-1", "new-2")
    assert initial == original_initial
    assert additional == original_additional


def test_source_priority_keeps_initial_order_when_additional_hits_are_duplicates():
    initial = [_source(f"same-{index}", f"Evidence {index}.") for index in range(2)]
    duplicate_additional = [dict(source) for source in initial]
    selected_file_ids = {str(source["file_id"]) for source in initial}

    ordered_ids = prioritize_evidence_sources(
        initial,
        duplicate_additional,
        selected_file_ids=selected_file_ids,
        max_sources=4,
    )

    assert ordered_ids == ("same-0", "same-1")


def test_source_priority_caps_ranked_subset_but_rejects_overflowing_candidate_set():
    initial = [_source(f"old-{index}", f"Initial evidence {index}.") for index in range(33)]
    additional = [_source(f"new-{index}", f"Additional evidence {index}.") for index in range(32)]
    selected_file_ids = {str(source["file_id"]) for source in [*initial, *additional]}

    with pytest.raises(InvalidInput, match="source limit"):
        prioritize_evidence_sources(
            initial,
            additional,
            selected_file_ids=selected_file_ids,
            max_sources=4,
        )
