#!/usr/bin/env python3
"""End-to-end Docling chunking and hybrid retrieval demo using production code paths.

Generates an in-memory synthetic PDF, parses it with Docling, persists artifacts
inside a TemporaryDirectory only, builds a keyword + Ollama embedding index, and
runs exact and semantic queries. Prints a concise stage-by-stage JSON report.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))

EMBEDDING_MODEL = "nomic-embed-text"
EXACT_IDENTIFIER = "Z7X-CAL-9001"
TEXT_PREVIEW_CHARS = 160

# Semantic query avoids the indexed wording; targets the signal-conditioning section.
EXACT_QUERY = EXACT_IDENTIFIER
SEMANTIC_QUERY = (
    "How are tiny transducer millivolt readings scaled before normalization?"
)


def _token_count(text: str, model: str) -> int:
    from lab.embedding_config import count_embedding_tokens

    return count_embedding_tokens(text, model, role="document")


def synthetic_pdf() -> bytes:
    """Multi-page PDF with headings, an exact id, paraphrasable prose, and a flow diagram."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setTitle("Learning Lab chunking demo")

    # Page 1 — introduction and exact identifier
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(72, 740, "Chunking Demonstration Protocol")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(72, 710, "1. Introduction")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 685, f"Calibration reference token: {EXACT_IDENTIFIER}.")
    pdf.drawString(72, 665, "Store this identifier verbatim for keyword retrieval checks.")
    pdf.drawString(72, 645, "Reference: https://example.com/chunking-demo")
    pdf.linkURL("https://example.com/chunking-demo", (72, 641, 320, 649), relative=0)
    pdf.showPage()

    # Page 2 — paraphrasable concept under a second heading
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(72, 740, "2. Signal Conditioning")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(
        72,
        715,
        "The pre-amplifier stage rescales millivolt-level transducer output before downstream normalization.",
    )
    pdf.drawString(72, 695, "Noise rejection happens after gain staging and before digitization.")
    pdf.drawString(72, 675, "This section supports semantic retrieval without repeating the exact identifier.")
    pdf.showPage()

    # Page 3 — vector flow diagram
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(72, 740, "3. Vector Flow Architecture")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 715, "Figure: end-to-end signal path used by the calibration bench.")
    y = 620
    boxes = [("Sensor", 72), ("Pre-amp", 210), ("Normalizer", 348), ("ADC", 486)]
    for label, x in boxes:
        pdf.rect(x, y, 96, 36)
        pdf.drawCentredString(x + 48, y + 14, label)
    for left, right in zip(boxes, boxes[1:]):
        x1 = left[1] + 96
        x2 = right[1]
        mid_y = y + 18
        pdf.line(x1, mid_y, x2, mid_y)
        pdf.line(x2 - 8, mid_y + 4, x2, mid_y)
        pdf.line(x2 - 8, mid_y - 4, x2, mid_y)
    pdf.showPage()

    pdf.save()
    return buffer.getvalue()


def _fail(message: str, *, hint: str | None = None) -> None:
    payload = {"error": message}
    if hint:
        payload["hint"] = hint
    print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


def _require_docling_artifacts() -> str:
    path = os.environ.get("DOCLING_ARTIFACTS_PATH", "").strip()
    if not path:
        _fail(
            "DOCLING_ARTIFACTS_PATH is not set.",
            hint="Run from Code with DOCLING_ARTIFACTS_PATH=data/external/modelweights/docling "
            "after `make docling-models`.",
        )
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        _fail(
            f"DOCLING_ARTIFACTS_PATH does not exist: {resolved}",
            hint="Run `make docling-models` from Code on a network that permits huggingface.co.",
        )
    if not any(resolved.iterdir()):
        _fail(
            f"DOCLING_ARTIFACTS_PATH is empty: {resolved}",
            hint="Run `make docling-models` from Code to download layout and table models.",
        )
    return str(resolved)


async def _require_ollama_embedding(model: str) -> None:
    from lab import models

    try:
        await models.embed_texts(["preflight"], model)
    except ValueError as exc:
        _fail(str(exc), hint=f"Verify `ollama pull {model}` succeeded and Ollama can embed text.")
    except Exception as exc:
        _fail(
            f"Embedding preflight failed ({type(exc).__name__}: {exc}).",
            hint=f"Check Ollama logs and confirm {model!r} supports POST /api/embed.",
        )


def _chunk_preview(chunk: dict[str, Any]) -> dict[str, Any]:
    text = str(chunk.get("text") or "")
    preview = text[:TEXT_PREVIEW_CHARS]
    if len(text) > TEXT_PREVIEW_CHARS:
        preview += "…"
    return {
        "chunk_id": chunk.get("chunk_id"),
        "chunk_index": chunk.get("chunk_index"),
        "headings": chunk.get("headings") or [],
        "pages": chunk.get("pages") or [],
        "token_count": _token_count(text, EMBEDDING_MODEL),
        "text_preview": preview,
        "asset_ids": chunk.get("asset_ids") or [],
    }


def _hit_payload(hit: dict[str, Any]) -> dict[str, Any]:
    text = str(hit.get("text") or "")
    preview = text[:TEXT_PREVIEW_CHARS]
    if len(text) > TEXT_PREVIEW_CHARS:
        preview += "…"
    return {
        "chunk_id": hit["chunk_id"],
        "chunk_index": hit.get("chunk_index"),
        "headings": hit.get("headings") or [],
        "pages": hit.get("pages") or [],
        "text_preview": preview,
        "trace": hit.get("trace", {}),
    }


def _citation_payload(citation: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": citation.get("chunk_id"),
        "headings": citation.get("headings") or [],
        "pages": citation.get("pages") or [],
        "assets": citation.get("assets") or [],
        "trace": citation.get("trace", {}),
    }


def _setup_temp_store(scratch: Path) -> tuple[Any, str, str]:
    from lab.storage import Store, write_json

    root = scratch / "demo_topics"
    settings = scratch / "settings.json"
    topic_id = f"chunking-demo-{uuid.uuid4().hex[:12]}"
    topic_path = root / topic_id
    topic_path.mkdir(parents=True)
    write_json(topic_path / "topic.json", {"id": topic_id, "name": "Chunking demo"})
    write_json(topic_path / "files.json", [])
    write_json(settings, {})
    return Store(root, settings), topic_id, topic_id


async def _run_demo() -> dict[str, Any]:
    from lab import models
    from lab.parse_pipeline import parse_and_persist
    from lab.retrieval import evidence_messages, index_chunks, search

    artifacts_path = _require_docling_artifacts()
    await _require_ollama_embedding(EMBEDDING_MODEL)

    pdf_bytes = synthetic_pdf()
    file_id = uuid.uuid4().hex
    filename = "chunking_demo.pdf"
    original_name = f"2026_09_23_chunking-demo-{file_id}.pdf"

    with TemporaryDirectory(prefix="learning-lab-chunking-demo-") as scratch_name:
        scratch = Path(scratch_name).resolve()
        store, topic, _ = _setup_temp_store(scratch)

        updates, index_records = parse_and_persist(
            store,
            topic,
            data=pdf_bytes,
            filename=filename,
            original_name=original_name,
            file_id=file_id,
            embedding_model=EMBEDDING_MODEL,
        )

        index_result = await index_chunks(
            store,
            topic,
            file_id,
            index_records,
            embedding_model=EMBEDDING_MODEL,
            embedder=models.embed_texts,
        )
        if index_result.get("mode") != "hybrid":
            warning = index_result.get("warning") or "Hybrid index was not created."
            _fail(
                warning,
                hint=f"Ensure Ollama is running and `ollama pull {EMBEDDING_MODEL}` completed.",
            )

        chunk_rows = [_chunk_preview(record) for record in index_records]
        queries: list[dict[str, Any]] = []
        for kind, query in (("exact", EXACT_QUERY), ("semantic", SEMANTIC_QUERY)):
            result = await search(
                store,
                topic,
                query,
                file_ids=[file_id],
                limit=4,
                embedding_model=EMBEDDING_MODEL,
                embedder=models.embed_texts,
            )
            hits = [_hit_payload(hit) for hit in result.get("hits") or []]
            messages, citations = evidence_messages(
                store, topic, result.get("hits") or [], include_images=False,
            )
            queries.append({
                "kind": kind,
                "query": query,
                "mode": result.get("mode"),
                "warning": result.get("warning"),
                "hits": hits,
                "selected_evidence": [_citation_payload(item) for item in citations],
                "evidence_message_count": len(messages),
            })

        return {
            "workspace": str(scratch),
            "docling_artifacts_path": artifacts_path,
            "embedding_model": EMBEDDING_MODEL,
            "parse": {
                "parser_version": updates.get("parser_version"),
                "page_count": updates.get("page_count"),
                "figure_count": updates.get("asset_count"),
                "warnings": updates.get("warnings") or [],
                "markdown_chars": len(
                    (store.file_path(topic, updates["markdown_name"]).read_text(encoding="utf-8"))
                ),
                "persisted_artifacts": sorted(
                    path.name
                    for path in store.topic(topic).iterdir()
                    if path.is_file() and path.name != "topic.json"
                ),
            },
            "chunks": chunk_rows,
            "index": {
                "mode": index_result.get("mode"),
                "inserted": index_result.get("inserted"),
                "embedded": index_result.get("embedded"),
                "file_id": file_id,
            },
            "queries": queries,
        }


def main() -> None:
    report = asyncio.run(_run_demo())
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
