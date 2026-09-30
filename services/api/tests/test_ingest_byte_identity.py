"""Synthetic parse outputs must stay byte-identical across repeated runs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lab import chunking, parse_pipeline
from lab.docling_pipeline import ImageAsset, ParseArtifacts
from lab.storage import Store


def _synthetic_parse(monkeypatch, tmp_path):
    code_source = 'def choose(flag):\n    if flag:\n        return "ready"\n    else:\n        return "stop"\n'
    tokenizer = SimpleNamespace(count_tokens=len)
    asset = ImageAsset(
        id="figure_0",
        filename="figure.png",
        data=b"png",
        kind="figure",
        page=1,
        bbox=None,
        caption="captiontextlong",
        doc_ref="#/pictures/0",
    )
    parsed = ParseArtifacts(
        markdown="# Figure",
        docling={"name": "sample", "texts": []},
        images=[asset],
        warnings=[],
        parser_version="2.127.0",
        document=SimpleNamespace(pages={1: None, 2: None, 3: None, 4: None}),
    )
    pdf = b"%PDF-1.7 synthetic fixture bytes for hashing"
    monkeypatch.setattr(parse_pipeline, "parse_pdf_bytes", lambda *args, **kwargs: parsed)
    monkeypatch.setattr(parse_pipeline, "chunk_tokenizer", lambda model, **kwargs: (tokenizer, []))
    monkeypatch.setattr(
        parse_pipeline,
        "chunk_docling_document",
        lambda *args, **kwargs: (
            [
                {
                    "index": 0,
                    "text": code_source,
                    "contextualized_text": code_source,
                    "headings": [],
                    "pages": [],
                    "bboxes": [],
                    "picture_asset_ids": [],
                }
            ],
            [],
        ),
    )
    monkeypatch.setattr(chunking, "chunk_embed_token_limit", lambda model: 8)
    store = Store(tmp_path / "topics", tmp_path / "settings.json")
    topic = store.create("Byte identity")["id"]
    updates, _records = parse_pipeline.parse_and_persist(
        store,
        topic,
        data=pdf,
        filename="figure.pdf",
        original_name="2026_09_30_figure.pdf",
        file_id="file1",
    )
    chunks_path = store.file_path(topic, updates["chunks_name"])
    parse_path = store.file_path(topic, updates["parse_name"])
    return chunks_path.read_bytes(), parse_path.read_bytes()


def test_parse_persist_chunk_and_manifest_bytes_are_stable(monkeypatch, tmp_path):
    first_chunks, first_manifest = _synthetic_parse(monkeypatch, tmp_path / "run1")
    second_chunks, second_manifest = _synthetic_parse(monkeypatch, tmp_path / "run2")
    assert first_chunks == second_chunks
    assert first_manifest == second_manifest
    assert first_chunks.endswith(b"\n")
    assert b"file1:text:000000" in first_chunks
