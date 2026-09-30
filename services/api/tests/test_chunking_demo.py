"""Focused tests for scripts/chunking_demo.py helpers (no Learning/ access)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "chunking_demo.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("chunking_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    sys.path.insert(0, str(ROOT / "services/api"))
    return _load_demo()


def test_synthetic_pdf_is_multipage(demo):
    data = demo.synthetic_pdf()
    assert data.startswith(b"%PDF-")
    assert len(data) > 2000
    # ReportLab emits one /Type /Page object per canvas page.
    assert data.count(b"/Type /Page") >= 3
    assert demo.EXACT_QUERY == demo.EXACT_IDENTIFIER
    assert demo.EXACT_IDENTIFIER not in demo.SEMANTIC_QUERY


def test_token_count_uses_embedding_config(demo, monkeypatch):
    from lab import embedding_config

    monkeypatch.setattr(
        embedding_config,
        "count_embedding_tokens",
        lambda text, model, role="document": 42,
    )
    assert demo._token_count("anything", "nomic-embed-text") == 42


def test_require_docling_artifacts_missing_env(demo, monkeypatch):
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)
    with pytest.raises(SystemExit) as exc:
        demo._require_docling_artifacts()
    assert exc.value.code == 1


def test_require_docling_artifacts_empty_dir(demo, monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", str(empty))
    with pytest.raises(SystemExit):
        demo._require_docling_artifacts()


def test_chunk_preview_truncates_long_text(demo):
    record = {
        "chunk_id": "demo:000",
        "chunk_index": 0,
        "text": "x" * 300,
        "headings": ["Intro"],
        "pages": [1],
        "asset_ids": [],
    }
    preview = demo._chunk_preview(record)
    assert preview["token_count"] > 0
    assert preview["text_preview"].endswith("…")
    assert len(preview["text_preview"]) == demo.TEXT_PREVIEW_CHARS + 1
