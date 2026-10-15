"""Answer-or-search prompt plans bound to retained indexed evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from copy import deepcopy
from typing import TypedDict

from lab.chat_prompt import build_chat_prompt
from lab.contracts import ChatPromptPlan, Citation
from lab.errors import InvalidInput
from lab.evidence_request import MAX_SOURCE_REFERENCES, SourceReference, build_source_manifest, merge_scoped_sources

_INITIAL_INSTRUCTION = (
    "Return the requested structured answer-or-search action. Answer only from supplied evidence and declare "
    "the source labels that support the answer. If an important part of the question needs evidence from the "
    "selected indexed documents that is not supplied, you may request one additional selected-document search. "
    "Do not invent labels or treat a source label as proof beyond its indexed source identity."
)
_FINAL_INSTRUCTION = (
    "Return the requested structured answer using the supplied retained evidence and declare only source labels "
    "that support the answer. Do not request another search. State what remains unsupported instead of inventing "
    "facts or labels."
)


class EvidencePromptPlan(ChatPromptPlan):
    """A normal context-budgeted prompt plus the exact retained source identities."""

    source_manifest: tuple[SourceReference, ...]


def build_initial_evidence_prompt(
    *,
    prompt_kwargs: Mapping[str, object],
    source_chunks: Sequence[Mapping[str, object]],
    selected_file_ids: Set[str],
) -> EvidencePromptPlan:
    """Build a first answer-or-search prompt from explicitly selected indexed evidence."""
    candidates = merge_scoped_sources(
        source_chunks,
        (),
        selected_file_ids=selected_file_ids,
        max_sources=MAX_SOURCE_REFERENCES,
    )
    return _build_evidence_prompt(prompt_kwargs, candidates, _INITIAL_INSTRUCTION)


def build_final_evidence_prompt(
    *,
    prompt_kwargs: Mapping[str, object],
    initial_chunks: Sequence[Mapping[str, object]],
    additional_chunks: Sequence[Mapping[str, object]],
    selected_file_ids: Set[str],
    max_sources: int,
) -> EvidencePromptPlan:
    """Build the final answer prompt after deterministic balancing of both search stages."""
    ordered_ids = prioritize_evidence_sources(
        initial_chunks,
        additional_chunks,
        selected_file_ids=selected_file_ids,
        max_sources=max_sources,
    )
    all_chunks = merge_scoped_sources(
        initial_chunks,
        additional_chunks,
        selected_file_ids=selected_file_ids,
        max_sources=MAX_SOURCE_REFERENCES,
    )
    chunks_by_id = {str(chunk["chunk_id"]): chunk for chunk in all_chunks}
    ordered_chunks = tuple(chunks_by_id[chunk_id] for chunk_id in ordered_ids)
    return _build_evidence_prompt(
        prompt_kwargs,
        ordered_chunks,
        _FINAL_INSTRUCTION,
        validation_chunks=all_chunks,
    )


def prioritize_evidence_sources(
    initial_chunks: Sequence[Mapping[str, object]],
    additional_chunks: Sequence[Mapping[str, object]],
    *,
    selected_file_ids: Set[str],
    max_sources: int,
) -> tuple[str, ...]:
    """Validate the full candidate set, then rank novel follow-up and initial hits alternately."""
    if type(max_sources) is not int or not 1 <= max_sources <= MAX_SOURCE_REFERENCES:
        raise InvalidInput("The final evidence source limit must be a positive bounded integer.")
    initial = merge_scoped_sources(
        initial_chunks,
        (),
        selected_file_ids=selected_file_ids,
        max_sources=MAX_SOURCE_REFERENCES,
    )
    merged = merge_scoped_sources(
        initial_chunks,
        additional_chunks,
        selected_file_ids=selected_file_ids,
        max_sources=MAX_SOURCE_REFERENCES,
    )
    initial_ids = {str(chunk["chunk_id"]) for chunk in initial}
    initial_order = [str(chunk["chunk_id"]) for chunk in initial]
    additional_order = [str(chunk["chunk_id"]) for chunk in merged if chunk["chunk_id"] not in initial_ids]
    if not additional_order:
        return tuple(initial_order[:max_sources])

    balanced: list[str] = []
    additional_index = 0
    initial_index = 0
    while len(balanced) < max_sources and (
        additional_index < len(additional_order) or initial_index < len(initial_order)
    ):
        if additional_index < len(additional_order):
            balanced.append(additional_order[additional_index])
            additional_index += 1
        if len(balanced) < max_sources and initial_index < len(initial_order):
            balanced.append(initial_order[initial_index])
            initial_index += 1
    return tuple(balanced)


def _build_evidence_prompt(
    prompt_kwargs: Mapping[str, object],
    ordered_chunks: Sequence[Mapping[str, object]],
    trusted_instruction: str,
    *,
    validation_chunks: Sequence[Mapping[str, object]] | None = None,
) -> EvidencePromptPlan:
    sources_by_id = {
        str(chunk["chunk_id"]): chunk
        for chunk in (validation_chunks if validation_chunks is not None else ordered_chunks)
    }
    evidence_by_id, citations_by_id = _aligned_prompt_pairs(prompt_kwargs, sources_by_id)
    manifest = build_source_manifest(ordered_chunks)
    labels_by_id = {reference.source_id: reference.label for reference in manifest}
    labeled_evidence = []
    labeled_citations: list[Citation] = []
    for reference in manifest:
        source_id = reference.source_id
        source = sources_by_id[source_id]
        evidence = evidence_by_id[source_id]
        label_header = _source_header(reference)
        labeled_evidence.append({**evidence, "content": f"{label_header}\n{evidence['content']}"})
        labeled_citations.append({**citations_by_id[source_id], "source_label": labels_by_id[source_id]})

    prepared_kwargs = deepcopy(dict(prompt_kwargs))
    prepared_kwargs["evidence"] = labeled_evidence
    prepared_kwargs["citations"] = labeled_citations
    prepared_kwargs["trusted_extra_instruction"] = trusted_instruction
    plan = build_chat_prompt(**prepared_kwargs)
    retained_ids = {citation["chunk_id"] for citation in plan["citations"]}
    retained_manifest = tuple(reference for reference in manifest if reference.source_id in retained_ids)
    final_citations = [
        {**citation, "source_label": labels_by_id[str(citation["chunk_id"])]} for citation in plan["citations"]
    ]
    return {
        **plan,
        "citations": final_citations,
        "retrieval_record": {**plan["retrieval_record"], "citations": final_citations},
        "source_manifest": retained_manifest,
    }


def _aligned_prompt_pairs(
    prompt_kwargs: Mapping[str, object], sources_by_id: Mapping[str, Mapping[str, object]]
) -> tuple[dict[str, dict[str, object]], dict[str, Citation]]:
    expected_ids = set(sources_by_id)
    evidence, citations = prompt_kwargs.get("evidence"), prompt_kwargs.get("citations")
    if (
        isinstance(evidence, (str, bytes))
        or not isinstance(evidence, Sequence)
        or isinstance(citations, (str, bytes))
        or not isinstance(citations, Sequence)
        or len(evidence) != len(citations)
    ):
        raise InvalidInput("Evidence messages and source citations must be aligned sequences.")
    evidence_by_id: dict[str, dict[str, object]] = {}
    citations_by_id: dict[str, Citation] = {}
    for raw_message, raw_citation in zip(evidence, citations, strict=True):
        if not isinstance(raw_message, Mapping) or not isinstance(raw_citation, Mapping):
            raise InvalidInput("Each evidence message must match an indexed source citation.")
        source_id = raw_citation.get("chunk_id")
        if not isinstance(source_id, str) or source_id not in expected_ids or source_id in citations_by_id:
            raise InvalidInput("Evidence citations must match unique supplied indexed source IDs.")
        source = sources_by_id[source_id]
        if (
            raw_citation.get("file_id") != source.get("file_id")
            or raw_citation.get("file_name") != source.get("file_name")
            or raw_citation.get("pages") != source.get("pages")
        ):
            raise InvalidInput("A source citation's panel identity differs from its indexed source.")
        content = raw_message.get("content")
        full_text = source.get("text")
        if (
            raw_message.get("role") != "user"
            or not isinstance(content, str)
            or not isinstance(full_text, str)
            or full_text not in content
        ):
            raise InvalidInput("The full indexed source text must appear in its matched evidence message.")
        evidence_by_id[source_id] = dict(raw_message)
        citations_by_id[source_id] = _checked_citation(raw_citation)
    if set(citations_by_id) != expected_ids:
        raise InvalidInput("Every supplied indexed source must have one matching evidence message and citation.")
    return evidence_by_id, citations_by_id


def _checked_citation(value: Mapping[str, object]) -> Citation:
    chunk_id, file_id, file_name = value.get("chunk_id"), value.get("file_id"), value.get("file_name")
    headings, pages = value.get("headings"), value.get("pages")
    bboxes, assets, trace, text = (
        value.get("bboxes"),
        value.get("assets"),
        value.get("trace"),
        value.get("text"),
    )
    if (
        not all(isinstance(item, str) for item in (chunk_id, file_id, file_name, text))
        or not isinstance(headings, list)
        or any(not isinstance(item, str) for item in headings)
        or not isinstance(pages, list)
        or any(type(page) is not int for page in pages)
        or not isinstance(bboxes, list)
        or any(not isinstance(box, dict) for box in bboxes)
        or not isinstance(assets, list)
        or any(not isinstance(asset, str) for asset in assets)
        or not isinstance(trace, dict)
    ):
        raise InvalidInput("A source citation has invalid panel or trace metadata.")
    checked: Citation = {
        "chunk_id": chunk_id,
        "file_id": file_id,
        "file_name": file_name,
        "headings": headings,
        "pages": pages,
        "bboxes": bboxes,
        "assets": assets,
        "trace": trace,
        "text": text,
    }
    chunk_index = value.get("chunk_index")
    if chunk_index is not None:
        if type(chunk_index) is not int or chunk_index < 0:
            raise InvalidInput("A source citation has an invalid chunk index.")
        checked["chunk_index"] = chunk_index
    return checked


def _source_header(reference: SourceReference) -> str:
    pages = ", ".join(str(page) for page in reference.pages) or "unspecified"
    return f"[{reference.label}] Indexed source: {reference.file_name}; pages {pages}."
