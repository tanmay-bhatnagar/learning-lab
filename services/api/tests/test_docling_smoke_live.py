"""Docling smoke when local model artifacts are installed."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "data/external/modelweights/docling"
SMOKE = ROOT / "scripts/smoke_docling.py"


@pytest.mark.skipif(not ARTIFACTS.is_dir() or not any(ARTIFACTS.iterdir()), reason="Docling artifacts missing")
def test_docling_smoke_runs_on_synthetic_pdf(monkeypatch):
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", str(ARTIFACTS))
    spec = importlib.util.spec_from_file_location("smoke_docling", SMOKE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.main()
