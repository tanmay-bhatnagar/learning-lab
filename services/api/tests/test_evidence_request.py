"""Pure contracts for bounded answer-or-search evidence requests."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from lab.errors import InvalidInput
from lab.evidence_request import (
    AnswerAction,
    SearchSelectedAction,
    build_source_manifest,
    evidence_action_schema,
    merge_scoped_sources,
    parse_evidence_action,
)


def _source(chunk_id: str, file_id: str, text: str) -> dict[str, str]:
    return {"chunk_id": chunk_id, "file_id": file_id, "text": text}


def _manifest():
    return build_source_manifest(
        [
            _source("chunk-a", "paper-a", "Initial evidence A."),
            _source("chunk-b", "paper-b", "Initial evidence B."),
        ]
    )


def test_schema_is_one_strict_object_with_manifest_scoped_references():
    schema = evidence_action_schema([item.label for item in _manifest()])

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"action", "answer", "source_labels", "query"}
    assert schema["properties"]["action"]["enum"] == ["answer", "search_selected"]
    assert schema["properties"]["source_labels"]["items"]["enum"] == ["E1", "E2"]
    assert schema["properties"]["query"]["maxLength"] == 500
    assert schema["properties"]["answer"]["maxLength"] >= 16_000


def test_complete_answer_resolves_only_exact_initial_manifest_and_preserves_text():
    manifest = _manifest()
    markdown = "## Result\n\nThe estimate is 2.0 [E1].\n\n### Caveat\n\nSmall sample [E2]."
    raw = json.dumps({"action": "answer", "answer": markdown, "source_labels": ["E1", "E2"], "query": ""})

    result = parse_evidence_action(raw, manifest, can_search=True)

    assert result == AnswerAction(markdown=markdown, references=(manifest[0], manifest[1]))
    assert result.markdown == markdown
    assert result.references[0].source_id == "chunk-a"
    assert result.references[1].content_sha256 == hashlib.sha256(b"Initial evidence B.").hexdigest()


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "answer", "answer": " ", "source_labels": ["E1"], "query": ""},
        {"action": "answer", "answer": "A [E1]", "source_labels": ["unknown"], "query": ""},
        {"action": "answer", "answer": "A [E1]", "source_labels": ["E1", "E1"], "query": ""},
        {"action": "answer", "answer": "A [E1]", "source_labels": [], "query": ""},
        {"action": "answer", "answer": "A [E1]", "source_labels": ["E1"], "query": "search too"},
        {"action": "answer", "answer": "A [E1]", "source_labels": ["E1"], "query": "", "file_id": "paper-a"},
        {"action": "search_selected", "answer": "not blank", "source_labels": [], "query": "term"},
        {"action": "search_selected", "answer": "", "source_labels": ["E1"], "query": "term"},
        {"action": "search_selected", "answer": "", "source_labels": [], "query": " "},
        {"action": "search_selected", "answer": "", "source_labels": [], "query": "q" * 501},
        {"action": "search_selected", "answer": "", "source_labels": [], "query": "q\nforbidden"},
        {"action": "arbitrary_operation", "answer": "", "source_labels": [], "query": ""},
    ],
)
def test_rejects_mixed_empty_unknown_or_out_of_scope_actions(payload):
    with pytest.raises(InvalidInput):
        parse_evidence_action(payload, _manifest(), can_search=True)


def test_rejects_truncated_malformed_oversized_and_controlled_json():
    manifest = _manifest()
    with pytest.raises(InvalidInput):
        parse_evidence_action('{"action":"answer","answer":"partial', manifest, can_search=True)
    with pytest.raises(InvalidInput):
        parse_evidence_action("not json", manifest, can_search=True)
    with pytest.raises(InvalidInput):
        parse_evidence_action(
            {"action": "answer", "answer": "A\x00 [E1]", "source_labels": ["E1"], "query": ""},
            manifest,
            can_search=True,
        )
    with pytest.raises(InvalidInput):
        parse_evidence_action(
            {"action": "answer", "answer": "A [E1]" * 20_000, "source_labels": ["E1"], "query": ""},
            manifest,
            can_search=True,
        )


def test_search_action_is_one_bounded_query_and_requires_nonempty_selected_scope():
    result = parse_evidence_action(
        {"action": "search_selected", "answer": "", "source_labels": [], "query": "Appendix B comparison"},
        _manifest(),
        can_search=True,
    )

    assert result == SearchSelectedAction(query="Appendix B comparison")
    with pytest.raises(InvalidInput):
        parse_evidence_action(
            {"action": "search_selected", "answer": "", "source_labels": [], "query": "Appendix B"},
            _manifest(),
            can_search=False,
        )
    with pytest.raises(InvalidInput):
        parse_evidence_action(
            {"action": "search_selected", "answer": "", "source_labels": [], "query": "Appendix B"},
            (),
            can_search=True,
        )


def test_merge_deduplicates_by_stable_id_preserves_order_and_does_not_mutate_inputs():
    initial = [_source("chunk-a", "paper-a", "Initial evidence A.")]
    additional = [
        _source("chunk-a", "paper-a", "Initial evidence A."),
        _source("chunk-b", "paper-a", "Follow-up evidence B."),
    ]
    initial_before, additional_before = deepcopy(initial), deepcopy(additional)

    merged = merge_scoped_sources(
        initial,
        additional,
        selected_file_ids=frozenset({"paper-a"}),
        max_sources=3,
    )

    assert [item["chunk_id"] for item in merged] == ["chunk-a", "chunk-b"]
    assert initial == initial_before
    assert additional == additional_before


@pytest.mark.parametrize("selected_file_ids", [None, frozenset(), frozenset({"paper-a", ""})])
def test_merge_rejects_empty_or_invalid_selected_file_scope(selected_file_ids):
    with pytest.raises(InvalidInput):
        merge_scoped_sources(
            [_source("chunk-a", "paper-a", "Initial evidence A.")],
            [],
            selected_file_ids=selected_file_ids,
            max_sources=3,
        )


def test_merge_rejects_out_of_scope_changed_identity_and_capacity_overflow():
    initial = [_source("chunk-a", "paper-a", "Initial evidence A.")]
    with pytest.raises(InvalidInput):
        merge_scoped_sources(
            initial,
            [_source("chunk-b", "paper-b", "Outside selected files.")],
            selected_file_ids=frozenset({"paper-a"}),
            max_sources=3,
        )
    with pytest.raises(InvalidInput):
        merge_scoped_sources(
            initial,
            [_source("chunk-a", "paper-a", "Changed evidence.")],
            selected_file_ids=frozenset({"paper-a"}),
            max_sources=3,
        )
    with pytest.raises(InvalidInput):
        merge_scoped_sources(
            initial,
            [_source("chunk-b", "paper-a", "Follow-up evidence B.")],
            selected_file_ids=frozenset({"paper-a"}),
            max_sources=1,
        )
