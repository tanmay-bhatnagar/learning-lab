"""Tests for offline embedding tokenizer registry and formatting."""
from __future__ import annotations

from pathlib import Path

import pytest

from lab import embedding_config


@pytest.fixture(autouse=True)
def clear_tokenizer_cache():
    embedding_config._load_hf_tokenizer.cache_clear()
    embedding_config._load_transformers_tokenizer.cache_clear()
    yield
    embedding_config._load_hf_tokenizer.cache_clear()
    embedding_config._load_transformers_tokenizer.cache_clear()


def test_nomic_model_registry_has_prefixes():
    config = embedding_config.embedding_model_config("nomic-embed-text:latest")
    assert config is not None
    assert config.document_prefix == "search_document: "
    assert config.query_prefix == "search_query: "
    assert config.tokenizer_dir == "bert-base-uncased"


def test_format_for_embedding_applies_prefix_once():
    text = "hello"
    model = "nomic-embed-text"
    once = embedding_config.format_for_embedding(text, model, role="document")
    twice = embedding_config.format_for_embedding(once, model, role="document")
    assert once == "search_document: hello"
    assert twice == once


def test_chunk_tokenizer_falls_back_without_files(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(embedding_config, "tokenizer_root", lambda: tmp_path)
    tokenizer, warnings = embedding_config.chunk_tokenizer("nomic-embed-text")
    assert warnings
    assert tokenizer.count_tokens("abcd") == 1


def test_tokenizer_loaders_leave_process_environment_unchanged(monkeypatch):
    import sys
    from types import ModuleType

    transformers = ModuleType("transformers")
    transformers.AutoTokenizer = type("AutoTokenizer", (), {
        "from_pretrained": staticmethod(lambda path, **kwargs: (path, kwargs)),
    })
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    package_names = ["docling_core", "docling_core.transforms",
                     "docling_core.transforms.chunker",
                     "docling_core.transforms.chunker.tokenizer"]
    for name in package_names:
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    hf_module = ModuleType("docling_core.transforms.chunker.tokenizer.huggingface")
    hf_module.HuggingFaceTokenizer = type("HuggingFaceTokenizer", (), {
        "from_pretrained": staticmethod(lambda path, **kwargs: (path, kwargs)),
    })
    monkeypatch.setitem(sys.modules, hf_module.__name__, hf_module)
    monkeypatch.setenv("HF_HUB_OFFLINE", "caller-value")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    before = dict(__import__("os").environ)

    assert embedding_config._load_transformers_tokenizer("/local/tokenizer") == (
        "/local/tokenizer", {"local_files_only": True},
    )
    assert embedding_config._load_hf_tokenizer("/local/tokenizer", 100) == (
        "/local/tokenizer", {"max_tokens": 100, "local_files_only": True},
    )
    assert dict(__import__("os").environ) == before


def test_failed_tokenizer_load_uses_one_fallback_for_chunk_counting(monkeypatch):
    from types import SimpleNamespace
    from lab import chunking

    monkeypatch.setattr(embedding_config, "_tokenizer_files_present", lambda path: True)
    monkeypatch.setattr(embedding_config, "_load_transformers_tokenizer",
                        lambda path: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(embedding_config, "_load_hf_tokenizer",
                        lambda *args: (_ for _ in ()).throw(AssertionError("retried failed loader")))
    monkeypatch.setattr(embedding_config, "tokenizer_root", lambda: Path("/tokenizers"))
    tokenizer, warnings = embedding_config.chunk_tokenizer("nomic-embed-text", chunk_token_limit=512)
    monkeypatch.setattr(chunking, "chunk_embed_token_limit", lambda model: 10)
    record = {"text": "a" * 100, "headings": [], "pages": [], "bboxes": [],
              "picture_asset_ids": [], "contextualized_text": "a" * 100}
    pieces = chunking._enforce_embed_limit(record, "nomic-embed-text", tokenizer=tokenizer)
    assert warnings
    assert "".join(piece["text"] for piece in pieces) == "a" * 100
    assert len(pieces) > 1


def test_embedding_format_metadata():
    meta = embedding_config.embedding_format_metadata("nomic-embed-text")
    assert meta is not None
    assert meta["version"] == embedding_config.EMBEDDING_FORMAT_VERSION
    assert meta["document_prefix"] == "search_document: "


def _load_download_script():
    import importlib.util

    path = Path(__file__).resolve().parents[3] / "scripts/download_embedding_tokenizer.py"
    spec = importlib.util.spec_from_file_location("download_embedding_tokenizer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gguf_vocab_converts_to_wordpiece():
    script = _load_download_script()
    converted = script._gguf_to_wordpiece(["[PAD]", "[unused0]", "\u2581the", "\u2581!", "ing", "]"])
    assert converted == ["[PAD]", "[unused0]", "the", "!", "##ing", "##]"]


def test_gguf_vocab_conversion_rejects_collisions():
    script = _load_download_script()
    with pytest.raises(RuntimeError):
        script._gguf_to_wordpiece(["\u2581a", "\u2581a"])


_TOKENIZER_INSTALLED = (
    Path(__file__).resolve().parents[3]
    / "data/external/modelweights/tokenizers/bert-base-uncased/tokenizer.json"
).is_file()
_PARITY_SAMPLES = [
    "search_document: hello world",
    "search_query: What is calibration?",
    "The pre-amplifier stage rescales millivolt-level transducer output before digitization.",
    "naïve café résumé, Z7X-CAL-9001 and softmax(QK^T/√d_k)V — 日本語 😀",
]


@pytest.mark.skipif(not _TOKENIZER_INSTALLED,
                    reason="Offline embedding tokenizer not installed; run make embedding-tokenizer")
def test_local_tokenizer_has_no_unknowns_for_plain_english():
    tokenizer = embedding_config._load_transformers_tokenizer(
        str(embedding_config.tokenizer_path("nomic-embed-text")))
    tokens = tokenizer.tokenize("search_document: what is the calibration of a transducer?")
    assert tokenizer.unk_token not in tokens


@pytest.mark.skipif(not _TOKENIZER_INSTALLED,
                    reason="Offline embedding tokenizer not installed; run make embedding-tokenizer")
def test_local_tokenizer_matches_ollama_when_available():
    import asyncio
    import httpx

    from lab import models
    from lab.embedding_config import count_embedding_tokens

    model = "nomic-embed-text"

    async def fetch(text: str) -> int | None:
        async with models._client() as client:
            response = await client.post(
                "/api/embed",
                json={"model": model, "input": [text], "truncate": False, "keep_alive": 0},
            )
            if response.status_code != 200:
                pytest.skip(f"Ollama unavailable: {response.text}")
            count = response.json().get("prompt_eval_count")
            return count if isinstance(count, int) else None

    for text in _PARITY_SAMPLES:
        try:
            ollama = asyncio.run(fetch(text))
        except httpx.HTTPError as exc:
            pytest.skip(f"Ollama unavailable: {exc}")
        assert ollama == count_embedding_tokens(text, model), text


@pytest.mark.skipif(not _TOKENIZER_INSTALLED,
                    reason="Offline embedding tokenizer not installed; run make embedding-tokenizer")
def test_chunk_tokenizer_counts_embedding_special_tokens_at_boundary(monkeypatch):
    from lab import chunking

    model = "nomic-embed-text"
    path = str(embedding_config.tokenizer_path(model))
    chunk_tokenizer = embedding_config._load_hf_tokenizer(path, 512)
    text = "boundary check with a few ordinary words"
    raw = chunk_tokenizer.count_tokens(text)
    complete = len(chunk_tokenizer.get_tokenizer().encode(text, add_special_tokens=True))
    assert complete == raw + 2
    monkeypatch.setattr(chunking, "chunk_embed_token_limit", lambda _: complete - 1)
    record = {"text": text, "contextualized_text": text, "headings": [], "pages": [],
              "bboxes": [], "picture_asset_ids": []}
    chunks = chunking._enforce_embed_limit(record, model, tokenizer=chunk_tokenizer)
    assert len(chunks) > 1
    assert all(embedding_config.count_with_chunk_tokenizer(
        chunk["text"], model, chunk_tokenizer,
    ) <= complete - 1 for chunk in chunks)
