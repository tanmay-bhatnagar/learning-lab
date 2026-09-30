"""Topic-scoped indexing, hybrid retrieval, and evidence assembly."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Awaitable, Callable

from .contracts import Citation, IndexedChunk, StoreProtocol
from .embedding_config import embedding_index_key, format_for_embedding
from .errors import EmbeddingUnavailable
from .index import TopicIndex
from .storage import read_bytes

# Embedders raise EmbeddingUnavailable when the model cannot serve requests and
# ValueError when the input or response is invalid.
Embedder = Callable[[list[str], str], Awaitable[list[list[float]]]]


def topic_index_path(store: StoreProtocol, topic: str) -> Path:
    return store.file_path(topic, "retrieval.sqlite")


async def index_chunks(
    store: StoreProtocol,
    topic: str,
    file_id: str,
    chunks: list[IndexedChunk],
    *,
    embedding_model: str = "",
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    """Replace one file's chunks, adding embeddings when a local model is available."""
    mode = "keyword"
    warning = None
    indexed = [dict(chunk) for chunk in chunks]
    if embedding_model and embedder:
        try:
            vectors: list[list[float]] = []
            texts = [format_for_embedding(chunk["text"], embedding_model, role="document") for chunk in indexed]
            for start in range(0, len(texts), 32):
                vectors.extend(await embedder(texts[start : start + 32], embedding_model))
            if len(vectors) != len(indexed):
                raise ValueError("Embedding service returned the wrong number of vectors.")
            for chunk, vector in zip(indexed, vectors, strict=True):
                chunk["embedding"] = vector
                chunk["embedding_model"] = embedding_index_key(embedding_model)
            mode = "hybrid"
        except EmbeddingUnavailable as exc:
            warning = f"Embedding index unavailable; keyword index only: {exc}"

    with TopicIndex(topic_index_path(store, topic)) as index:
        result = index.replace_file(file_id, indexed)
    return {
        **result,
        "mode": mode,
        "embedding_model": embedding_model if mode == "hybrid" else "",
        **({"warning": warning} if warning else {}),
    }


async def search(
    store: StoreProtocol,
    topic: str,
    query: str,
    *,
    file_ids: list[str] | None = None,
    limit: int = 6,
    embedding_model: str = "",
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    """Search keyword and embedding indexes with deterministic RRF fusion."""
    path = topic_index_path(store, topic)
    if not path.exists():
        return {"hits": [], "mode": "none", "warning": "This topic has not been indexed yet."}

    vector = None
    warning = None
    if embedding_model and embedder:
        try:
            vectors = await embedder(
                [format_for_embedding(query, embedding_model, role="query")],
                embedding_model,
            )
            vector = vectors[0]
        except (EmbeddingUnavailable, ValueError) as exc:
            # Query embedding is best-effort: long questions or a missing model fall back to keywords.
            warning = f"Semantic search unavailable; keyword retrieval was used: {exc}"

    used_opening_chunks_fallback = False
    with TopicIndex(path) as index:
        hits = index.hybrid_search(
            query,
            vector,
            file_ids=file_ids,
            limit=limit,
            vector_model=embedding_index_key(embedding_model) if vector is not None else None,
        )
        if not hits and file_ids:
            hits = index.get_chunks(file_ids=file_ids)[: min(limit, 2)]
            used_opening_chunks_fallback = bool(hits)
            for rank, hit in enumerate(hits, start=1):
                hit["trace"] = {
                    "keyword": {"rank": None, "score": None},
                    "embedding": {"rank": None, "score": None},
                    "fusion": {"rank": rank, "score": 0.0},
                }
            warning = warning or "No query match; using bounded opening chunks from the selected file."
    semantic = any(hit.get("trace", {}).get("embedding", {}).get("rank") is not None for hit in hits)
    mode = "hybrid" if semantic else ("fallback" if used_opening_chunks_fallback else "keyword")
    if vector is not None and hits and not semantic and not used_opening_chunks_fallback:
        warning = warning or (
            f"No stored embeddings match {embedding_index_key(embedding_model)}; keyword retrieval was used. "
            "Re-upload files indexed before a change of embedding model or format."
        )
    result = {"hits": hits, "mode": mode}
    if warning:
        result["warning"] = warning
    return result


def _load_hit_images(
    store: StoreProtocol,
    topic: str,
    hit: IndexedChunk,
    *,
    used_assets: set[str],
    image_count: int,
    max_images: int,
) -> tuple[list[str], list[str]]:
    images: list[str] = []
    attached: list[str] = []
    if image_count >= max_images:
        return images, attached
    for asset_name in hit.get("asset_ids") or []:
        if asset_name in used_assets or image_count + len(images) >= max_images:
            continue
        data = read_bytes(store.file_path(topic, asset_name))
        if len(data) > 8 * 1024 * 1024:
            continue
        images.append(base64.b64encode(data).decode("ascii"))
        used_assets.add(asset_name)
        attached.append(asset_name)
    return images, attached


def evidence_messages(
    store: StoreProtocol,
    topic: str,
    hits: list[IndexedChunk],
    *,
    include_images: bool,
    max_images: int = 2,
) -> tuple[list[dict[str, Any]], list[Citation]]:
    """Turn ranked hits into untrusted Ollama messages plus durable citations."""
    messages: list[dict[str, Any]] = []
    citations: list[Citation] = []
    used_assets: set[str] = set()
    image_count = 0
    for hit in hits:
        headings = " > ".join(hit.get("headings") or [])
        pages = ", ".join(str(page) for page in hit.get("pages") or [])
        location = ", ".join(part for part in [hit["file_name"], headings, f"page {pages}" if pages else ""] if part)
        content = f"UNTRUSTED RETRIEVED EVIDENCE ({location}):\n{hit['text']}"
        message: dict[str, Any] = {"role": "user", "content": content}
        attached: list[str] = []
        if include_images:
            images, attached = _load_hit_images(
                store, topic, hit, used_assets=used_assets, image_count=image_count, max_images=max_images
            )
            image_count += len(images)
            if images:
                message["images"] = images
        messages.append(message)
        raw_text = hit.get("text") or ""
        excerpt = raw_text[:600] + ("…" if len(raw_text) > 600 else "")
        citation: dict[str, Any] = {
            "chunk_id": hit["chunk_id"],
            "file_id": hit["file_id"],
            "file_name": hit["file_name"],
            "headings": hit.get("headings") or [],
            "pages": hit.get("pages") or [],
            "bboxes": hit.get("bboxes") or [],
            "assets": attached or hit.get("asset_ids") or [],
            "trace": hit.get("trace", {}),
            "text": excerpt,
        }
        if "chunk_index" in hit:
            citation["chunk_index"] = hit["chunk_index"]
        citations.append(citation)
    return messages, citations
