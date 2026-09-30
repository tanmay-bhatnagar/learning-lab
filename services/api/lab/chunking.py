"""HybridChunker adapter for DoclingDocument chunk export."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from lab.docling_pipeline import ImageAsset
from lab.contracts import ChunkRecord
from lab.embedding_config import (
    chunk_embed_token_limit,
    chunk_tokenizer,
    count_embedding_tokens,
    count_with_chunk_tokenizer,
)


def _bbox_to_dict(bbox: Any) -> dict[str, Any]:
    return bbox.model_dump(mode="json", by_alias=True, exclude_none=True)


def _picture_ref_map(image_assets: Sequence[ImageAsset] | None) -> dict[str, str]:
    if not image_assets:
        return {}
    return {asset.doc_ref: asset.id for asset in image_assets if asset.kind == "figure" and asset.doc_ref}


def _extract_pages_and_bboxes(doc_items: Any) -> tuple[list[int], list[dict[str, Any]]]:
    pages: list[int] = []
    bboxes: list[dict[str, Any]] = []
    seen_pages: set[int] = set()

    for item in doc_items:
        for prov in getattr(item, "prov", []) or []:
            if prov.page_no not in seen_pages:
                pages.append(prov.page_no)
                seen_pages.add(prov.page_no)
            bboxes.append({"page": prov.page_no, **_bbox_to_dict(prov.bbox)})

    pages.sort()
    return pages, bboxes


def _linked_picture_asset_ids(
    doc_items: Any,
    ref_to_asset: Mapping[str, str],
) -> list[str]:
    linked: list[str] = []
    seen: set[str] = set()

    for item in doc_items:
        ref = getattr(item, "self_ref", None)
        if not ref:
            continue
        asset_id = ref_to_asset.get(ref)
        if asset_id and asset_id not in seen:
            linked.append(asset_id)
            seen.add(asset_id)
            continue
        if type(item).__name__ == "PictureItem" and ref in ref_to_asset:
            asset_id = ref_to_asset[ref]
            if asset_id not in seen:
                linked.append(asset_id)
                seen.add(asset_id)

    return linked


def chunk_docling_document(
    document: Any,
    *,
    image_assets: Sequence[ImageAsset] | None = None,
    embedding_model: str = "",
    chunker: Any | None = None,
    tokenizer: Any | None = None,
    **chunker_kwargs: Any,
) -> tuple[list[ChunkRecord], list[str]]:
    """Chunk a DoclingDocument with HybridChunker into JSON-serializable records."""
    try:
        from docling.chunking import HybridChunker
    except ImportError as exc:
        raise ValueError("Install the backend dependencies for docling chunking, then try again.") from exc

    warnings: list[str] = []
    ref_to_asset = _picture_ref_map(image_assets)
    if chunker is None and "tokenizer" not in chunker_kwargs:
        if tokenizer is None:
            tokenizer, warnings = chunk_tokenizer(embedding_model)
        chunker_kwargs["tokenizer"] = tokenizer
    hybrid = chunker if chunker is not None else HybridChunker(**chunker_kwargs)

    chunks: list[ChunkRecord] = []
    for chunk in hybrid.chunk(document):
        doc_items = chunk.meta.doc_items
        pages, bboxes = _extract_pages_and_bboxes(doc_items)
        record = {
            "text": chunk.text,
            "contextualized_text": hybrid.contextualize(chunk),
            "headings": chunk.meta.headings,
            "pages": pages,
            "bboxes": bboxes,
            "picture_asset_ids": _linked_picture_asset_ids(doc_items, ref_to_asset),
        }
        chunks.extend(enforce_embed_limit(record, embedding_model, tokenizer=tokenizer))
    for index, record in enumerate(chunks):
        record["index"] = index
    return chunks, warnings


def _contextualize(headings: Sequence[str] | None, text: str) -> str:
    return "\n".join([*(headings or []), text])


def enforce_embed_limit(
    record: ChunkRecord, embedding_model: str, *, tokenizer: Any | None = None
) -> list[ChunkRecord]:
    """Split chunks that HybridChunker left above the embedding limit.

    HybridChunker's max_tokens is a merge target: joined sub-chunks can exceed
    it by a few tokens because WordPiece counts are not additive across joins.
    Split text pieces concatenate directly to the exact original source; no
    whitespace or separator is inserted or discarded.
    """
    limit = chunk_embed_token_limit(embedding_model)

    def token_count(text: str) -> int:
        contextual = _contextualize(record["headings"], text)
        if tokenizer is None:
            return count_embedding_tokens(contextual, embedding_model, role="document")
        return count_with_chunk_tokenizer(contextual, embedding_model, tokenizer)

    def fits(text: str) -> bool:
        return token_count(text) <= limit

    if fits(record["text"]):
        return [record]
    if token_count("") > limit:
        raise ValueError(
            f"Embedding headings for {embedding_model!r} exceed the {limit}-token limit; "
            "shorten or remove the headings before indexing."
        )
    source = record["text"]
    pieces: list[str] = []
    start = 0
    while start < len(source):
        low, high = start + 1, len(source)
        while low < high:
            mid = (low + high + 1) // 2
            if fits(source[start:mid]):
                low = mid
            else:
                high = mid - 1
        if not fits(source[start:low]):
            raise ValueError(
                f"Text cannot fit the {limit}-token embedding limit for {embedding_model!r} "
                "even when split into bounded character spans."
            )
        boundary = low
        for position in range(low - 1, start, -1):
            if source[position].isspace():
                candidate = position + 1
                if source[start:candidate].strip() and fits(source[start:candidate]):
                    boundary = candidate
                    break
        pieces.append(source[start:boundary])
        start = boundary
    return [
        {
            **record,
            "text": piece,
            "contextualized_text": _contextualize(record["headings"], piece),
            "split_for_embedding": True,
        }
        for piece in pieces
    ]
