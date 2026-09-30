"""Persist Docling's native artifacts and retrieval chunks beside an original PDF."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .chunking import _enforce_embed_limit, chunk_docling_document
from .docling_pipeline import parse_pdf_bytes
from .embedding_config import chunk_tokenizer, embedding_format_metadata
from .index import content_hash
from .storage import write_bytes, write_json, write_text


def _artifact_name(base: str, suffix: str) -> str:
    name = f"{base}.{suffix}"
    if Path(name).name != name:
        raise ValueError("Invalid derived artifact filename.")
    return name


def parse_and_persist(
    store,
    topic: str,
    *,
    data: bytes,
    filename: str,
    original_name: str,
    file_id: str,
    embedding_model: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse one immutable PDF and atomically retain rebuildable derived artifacts."""
    base = original_name[:-4]
    created: list[Path] = []
    try:
        parsed = parse_pdf_bytes(data, filename=filename)
        tokenizer, tokenizer_warnings = chunk_tokenizer(embedding_model)
        raw_chunks, chunk_warnings = chunk_docling_document(
            parsed.document,
            image_assets=parsed.images,
            embedding_model=embedding_model,
            tokenizer=tokenizer,
        )
        chunk_warnings = tokenizer_warnings + chunk_warnings

        asset_by_id: dict[str, dict[str, Any]] = {}
        for asset in parsed.images:
            stored_name = _artifact_name(base, asset.filename)
            path = store.file_path(topic, stored_name)
            write_bytes(path, asset.data)
            created.append(path)
            asset_by_id[asset.id] = {
                "id": asset.id,
                "name": stored_name,
                "kind": asset.kind,
                "page": asset.page,
                "bbox": asset.bbox,
                "caption": asset.caption,
                "doc_ref": asset.doc_ref,
            }

        docling_name = _artifact_name(base, "docling.json")
        markdown_name = f"{base}.md"
        chunks_name = _artifact_name(base, "chunks.jsonl")
        parse_name = _artifact_name(base, "parse.json")

        records: list[dict[str, Any]] = []
        serializable_chunks: list[dict[str, Any]] = []
        for chunk in raw_chunks:
            chunk_index = int(chunk["index"])
            text = str(chunk.get("contextualized_text") or chunk.get("text") or "")
            if not text.strip():
                continue
            asset_names = [
                asset_by_id[asset_id]["name"]
                for asset_id in chunk.get("picture_asset_ids", [])
                if asset_id in asset_by_id
            ]
            chunk_id = f"{file_id}:text:{chunk_index:06d}"
            record = {
                "chunk_id": chunk_id,
                "file_id": file_id,
                "file_name": filename,
                "chunk_index": len(records),
                "text": text,
                "headings": list(chunk.get("headings") or []),
                "pages": list(chunk.get("pages") or []),
                "bboxes": list(chunk.get("bboxes") or []),
                "asset_ids": asset_names,
                "content_hash": content_hash(text),
            }
            records.append(record)
            serializable_chunks.append({**chunk, "chunk_id": chunk_id, "asset_names": asset_names})

        for asset in parsed.images:
            if asset.kind != "figure" or not asset.caption:
                continue
            stored = asset_by_id[asset.id]
            text = asset.caption.strip()
            bounded = _enforce_embed_limit({
                "text": text, "contextualized_text": text, "headings": [],
                "pages": [asset.page] if asset.page is not None else [],
                "bboxes": ([{"page": asset.page, **asset.bbox}]
                           if asset.page is not None and asset.bbox else []),
                "picture_asset_ids": [asset.id],
            }, embedding_model, tokenizer=tokenizer)
            for bounded_chunk in bounded:
                bounded_text = bounded_chunk["contextualized_text"]
                chunk_index = len(records)
                chunk_id = f"{file_id}:figure:{asset.id}:{chunk_index}"
                record = {
                    "chunk_id": chunk_id,
                    "file_id": file_id,
                    "file_name": filename,
                    "chunk_index": chunk_index,
                    "text": bounded_text,
                    "headings": [],
                    "pages": bounded_chunk["pages"],
                    "bboxes": bounded_chunk["bboxes"],
                    "asset_ids": [stored["name"]],
                    "content_hash": content_hash(bounded_text),
                }
                records.append(record)
                serializable_chunks.append({
                    **bounded_chunk,
                    "index": chunk_index,
                    "chunk_id": chunk_id,
                    "text": bounded_chunk["text"],
                    "contextualized_text": bounded_text,
                    "asset_names": record["asset_ids"],
                    "kind": "figure",
                })

        if not records:
            raise ValueError("Docling produced no searchable chunks.")

        for name, writer, value in [
            (markdown_name, write_text, parsed.markdown),
            (docling_name, write_json, parsed.docling),
            (chunks_name, write_text, "\n".join(
                json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
                for chunk in serializable_chunks
            ) + "\n"),
        ]:
            path = store.file_path(topic, name)
            writer(path, value)
            created.append(path)

        parse_warnings = list(parsed.warnings) + list(chunk_warnings)
        manifest = {
            "schema_version": 1,
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "parser": "docling",
            "parser_version": parsed.parser_version,
            "options": {
                "ocr": False,
                "table_structure": True,
                "page_images": True,
                "picture_images": True,
            },
            "markdown_name": markdown_name,
            "docling_name": docling_name,
            "chunks_name": chunks_name,
            "assets": list(asset_by_id.values()),
            "warnings": parse_warnings,
        }
        if embedding_model:
            manifest["embedding_model"] = embedding_model
            embed_meta = embedding_format_metadata(embedding_model)
            if embed_meta:
                manifest["embedding_format"] = embed_meta
        parse_path = store.file_path(topic, parse_name)
        write_json(parse_path, manifest)
        created.append(parse_path)

        updates = {
            "markdown_name": markdown_name,
            "docling_name": docling_name,
            "chunks_name": chunks_name,
            "parse_name": parse_name,
            "content_sha256": manifest["source_sha256"],
            "parser_version": parsed.parser_version,
            "page_count": sum(1 for asset in parsed.images if asset.kind == "page"),
            "asset_count": sum(1 for asset in parsed.images if asset.kind == "figure"),
            "assets": list(asset_by_id.values()),
            "warnings": parse_warnings,
        }
        return updates, records
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
