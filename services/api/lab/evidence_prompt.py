"""Answer-or-search prompt plans bound to retained indexed evidence."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence, Set
from copy import deepcopy
import hashlib
from typing import TypedDict

from lab.chat_prompt import build_chat_prompt
from lab.contracts import ChatPromptPlan, Citation
from lab.errors import InvalidInput
from lab.evidence_request import (
    MAX_SOURCE_REFERENCES,
    SourceImageReference,
    SourceReference,
    build_source_manifest,
    merge_scoped_sources,
)

_INITIAL_INSTRUCTION = (
    "Return exactly one JSON action object with fields action, answer, source_labels, query. "
    'For an answer, use {"action":"answer","answer":"A complete Markdown answer.",'
    '"source_labels":["E1"],"query":""}. E1 is an example only: declare only labels actually supplied in '
    "the evidence above; the list may be empty or noncontiguous. If you use inline [E#] markers, each marker must "
    "be in source_labels. When no supplied source supports the answer, use an empty source_labels list and no "
    "[E#] markers. For a search, use "
    '{"action":"search_selected","answer":"","source_labels":[],"query":"one search query"}. '
    "Never fill query on an answer action or answer/source_labels on a search action. Never return both. You may "
    "request at most one additional selected-document search, with one query of at most 500 characters. Do not "
    "copy or rephrase the user's question as a search query. Do not invent facts. If the evidence cannot answer "
    "and no useful selected-document query is apparent, answer with an explicit limitation and empty "
    "source_labels. Never request a file, path, topic, or conversation identifier."
)
_FINAL_INSTRUCTION = (
    "Return a complete, user-facing Markdown answer; this final turn is prose, not a JSON action object. Use only "
    "the supplied retained evidence, cite study evidence by filename and page, and use [E#] markers only when the "
    "matching source label is supplied above. Do not request or imply another search. State what remains "
    "unsupported instead of inventing facts or labels."
)


class EvidencePromptPlan(ChatPromptPlan):
    """A normal context-budgeted prompt plus the exact retained source identities."""

    source_manifest: tuple[SourceReference, ...]
    supplied_images: tuple[SourceImageReference, ...]


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
    images_by_source = _supplied_image_references(evidence_by_id, citations_by_id, sources_by_id)
    manifest = build_source_manifest(ordered_chunks)
    labels_by_id = {reference.source_id: reference.label for reference in manifest}
    labeled_evidence = []
    labeled_citations: list[Citation] = []
    for reference in manifest:
        source_id = reference.source_id
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
    retained_images = tuple(
        image for source_id in labels_by_id if source_id in retained_ids for image in images_by_source[source_id]
    )
    return {
        **plan,
        "citations": final_citations,
        "retrieval_record": {**plan["retrieval_record"], "citations": final_citations},
        "source_manifest": retained_manifest,
        "supplied_images": retained_images,
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
            or raw_citation.get("headings") != source.get("headings", [])
            or raw_citation.get("bboxes") != source.get("bboxes", [])
        ):
            raise InvalidInput("A source citation's panel identity differs from its indexed source.")
        if "chunk_index" in raw_citation and raw_citation["chunk_index"] != source.get("chunk_index"):
            raise InvalidInput("A source citation's chunk position differs from its indexed source.")
        _validate_citation_assets(raw_citation.get("assets"), source.get("asset_ids", []))
        content = raw_message.get("content")
        full_text = source.get("text")
        if (
            raw_message.get("role") != "user"
            or not isinstance(content, str)
            or not isinstance(full_text, str)
            or full_text not in content
        ):
            raise InvalidInput("The full indexed source text must appear in its matched evidence message.")
        if not _is_source_excerpt(raw_citation.get("text"), full_text):
            raise InvalidInput("A source citation excerpt must match the beginning of its indexed source text.")
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


def _validate_citation_assets(assets: object, source_assets: object) -> None:
    if (
        not isinstance(assets, list)
        or any(not isinstance(asset, str) for asset in assets)
        or len(assets) != len(set(assets))
        or not isinstance(source_assets, list)
        or any(not isinstance(asset, str) for asset in source_assets)
    ):
        raise InvalidInput("A source citation has invalid or duplicate image asset names.")
    positions = [source_assets.index(asset) for asset in assets if asset in source_assets]
    if len(positions) != len(assets) or positions != sorted(positions):
        raise InvalidInput("A source citation lists image assets outside its indexed source or in a changed order.")


def _is_source_excerpt(excerpt: object, full_text: str) -> bool:
    if not isinstance(excerpt, str) or not excerpt:
        return False
    if full_text.startswith(excerpt):
        return True
    return excerpt.endswith("…") and len(excerpt) > 1 and full_text.startswith(excerpt[:-1])


def _supplied_image_references(
    evidence_by_id: Mapping[str, Mapping[str, object]],
    citations_by_id: Mapping[str, Citation],
    sources_by_id: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[SourceImageReference, ...]]:
    result: dict[str, tuple[SourceImageReference, ...]] = {}
    for source_id, message in evidence_by_id.items():
        images = message.get("images", [])
        if not isinstance(images, list) or any(not isinstance(image, str) for image in images):
            raise InvalidInput("Evidence message images must be a list of encoded image bytes.")
        assets = citations_by_id[source_id]["assets"]
        if not images:
            result[source_id] = ()
            continue
        if len(images) != len(assets):
            raise InvalidInput("Each supplied evidence image must match exactly one named source asset.")
        references = []
        for asset_name, encoded in zip(assets, images, strict=True):
            try:
                image_bytes = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise InvalidInput("A supplied evidence image is not valid base64 data.") from None
            if not image_bytes:
                raise InvalidInput("A supplied evidence image cannot be empty.")
            references.append(
                SourceImageReference(
                    source_id=source_id,
                    file_id=str(sources_by_id[source_id]["file_id"]),
                    asset_name=asset_name,
                    content_sha256=hashlib.sha256(image_bytes).hexdigest(),
                )
            )
        result[source_id] = tuple(references)
    return result


def _source_header(reference: SourceReference) -> str:
    pages = ", ".join(str(page) for page in reference.pages) or "unspecified"
    return f"[{reference.label}] Indexed source: {reference.file_name}; pages {pages}."
