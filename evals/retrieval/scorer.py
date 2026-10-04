"""Pure extraction and retrieval coverage scoring for anchored evidence groups."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_LINE_HYPHEN = re.compile(r"(?<=\w)[\-\u2010\u2011]\s*\n\s*(?=\w)")
_SPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Normalize typography, table separators, and whitespace without changing signs."""
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("−", "-").replace("|", " ")
    normalized = _LINE_HYPHEN.sub("", normalized)
    return _SPACE.sub(" ", normalized).strip()


def group_matches(group: Mapping[str, Any], chunks: Sequence[Mapping[str, Any]]) -> bool:
    """Match page and all phrases in one source chunk, preserving row association."""
    pages = set(group["pages"])
    anchors = [[normalize_text(phrase) for phrase in alternative] for alternative in group["anchor_alternatives"]]
    if any(not phrase for alternative in anchors for phrase in alternative):
        return False
    for chunk in chunks:
        chunk_pages = chunk.get("pages", [])
        if not isinstance(chunk_pages, list) or not pages.intersection(chunk_pages):
            continue
        text = normalize_text(str(chunk.get("text", "")))
        if any(all(_contains_anchor(text, phrase) for phrase in alternative) for alternative in anchors):
            return True
    return False


def _contains_anchor(text: str, phrase: str) -> bool:
    """Require token boundaries and prevent decimal/grouping suffix matches."""
    return re.search(rf"(?<![\w.]){re.escape(phrase)}(?!\w|[.,]\d)", text) is not None


def score_case(
    case: Mapping[str, Any],
    indexed_chunks: Sequence[Mapping[str, Any]],
    retrieved_hits: Sequence[Mapping[str, Any]],
    retained_ids: Iterable[str],
    *,
    top_k: int,
) -> dict[str, Any]:
    """Score extraction, ranked hits, and retained evidence with fixed gold denominators."""
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k must be a positive integer.")
    groups = case["evidence_groups"]
    if not isinstance(case.get("category"), str) or not case["category"].strip():
        raise ValueError("Scored case requires a nonempty category.")
    if len(retrieved_hits) > top_k:
        raise ValueError("Production retrieval returned more hits than the requested top_k bound.")
    _validate_ranked_hits(retrieved_hits)
    if case["kind"] == "unsupported":
        return {
            "case_id": case["id"],
            "category": case["category"],
            "kind": "unsupported",
            "status": "unsupported_diagnostic",
            "extraction": {"available_groups": None, "total_groups": 0, "coverage": None},
            "retrieval": _null_metrics(top_k),
            "retained": _null_metrics(top_k),
            "abstention": "not_assessed",
        }

    extracted = {group["id"] for group in groups if group_matches(group, indexed_chunks)}
    extraction = {
        "available_groups": len(extracted),
        "total_groups": len(groups),
        "coverage": len(extracted) / len(groups),
        "unavailable_group_ids": [group["id"] for group in groups if group["id"] not in extracted],
    }
    if len(extracted) != len(groups):
        return {
            "case_id": case["id"],
            "category": case["category"],
            "kind": "answerable",
            "status": "extraction_limited",
            "extraction": extraction,
            "retrieval": _null_metrics(top_k),
            "retained": _null_metrics(top_k),
        }

    ordered_hits = sorted(retrieved_hits, key=_rank)
    retained = set(retained_ids)
    retained_hits = [hit for hit in ordered_hits if hit.get("chunk_id") in retained]
    return {
        "case_id": case["id"],
        "category": case["category"],
        "kind": "answerable",
        "status": "scored",
        "extraction": extraction,
        "retrieval": _retrieval_metrics(groups, ordered_hits, top_k),
        "retained": _retrieval_metrics(groups, retained_hits, top_k),
    }


def _retrieval_metrics(
    groups: Sequence[Mapping[str, Any]], hits: Sequence[Mapping[str, Any]], top_k: int
) -> dict[str, Any]:
    relevant_ranks: dict[str, int] = {}
    for hit in hits:
        rank = _rank(hit)
        for group in groups:
            if group["id"] not in relevant_ranks and group_matches(group, [hit]):
                relevant_ranks[group["id"]] = rank
    covered = sum(rank <= top_k for rank in relevant_ranks.values())
    ranks = list(relevant_ranks.values())
    first_rank = min(ranks) if ranks else None
    return {
        "recall_at_k": covered / len(groups),
        "k": top_k,
        "first_relevant_rank": first_rank,
        "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
        "all_required_at_k": covered == len(groups),
        "covered_group_ids": [group["id"] for group in groups if relevant_ranks.get(group["id"], top_k + 1) <= top_k],
        "uncovered_group_ids": [group["id"] for group in groups if relevant_ranks.get(group["id"], top_k + 1) > top_k],
    }


def _rank(hit: Mapping[str, Any]) -> int:
    trace = hit.get("trace")
    fusion = trace.get("fusion") if isinstance(trace, Mapping) else None
    rank = fusion.get("rank") if isinstance(fusion, Mapping) else None
    if type(rank) is not int or rank < 1:
        raise ValueError("Every retrieval hit must contain a positive integer fusion rank.")
    return rank


def _validate_ranked_hits(hits: Sequence[Mapping[str, Any]]) -> None:
    ranks = [_rank(hit) for hit in hits]
    if len(set(ranks)) != len(ranks) or set(ranks) != set(range(1, len(ranks) + 1)):
        raise ValueError("Fusion ranks must be unique and contiguous within the returned hit list.")


def _null_metrics(top_k: int) -> dict[str, Any]:
    return {
        "recall_at_k": None,
        "k": top_k,
        "first_relevant_rank": None,
        "reciprocal_rank": None,
        "all_required_at_k": None,
        "covered_group_ids": [],
        "uncovered_group_ids": [],
    }
