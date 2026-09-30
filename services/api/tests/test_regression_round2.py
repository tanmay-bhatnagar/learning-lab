"""Round-2 audit regressions: config defaults, upload errors, stream messages, and isolation."""

from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from lab.config import CODE_ROOT, DEFAULT_EMBEDDING_TOKENIZER_ROOT, load_config
from lab.context import prepare_context, prepare_context_details
from lab.docling_pipeline import PARTIAL_SUCCESS_WARNING, ParserWarning
from lab.errors import CorruptData
from lab.models import OllamaGateway
from lab.web.app import create_app
from tests.fakes import FakeModel


def test_default_embedding_tokenizer_root_matches_original():
    config = load_config()
    expected = (CODE_ROOT / "data/external/modelweights/tokenizers").expanduser().resolve()
    assert config.embedding_tokenizer_root == expected
    assert config.embedding_tokenizer_root == DEFAULT_EMBEDDING_TOKENIZER_ROOT


def test_docling_artifacts_path_none_when_unset_or_empty(monkeypatch):
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)
    assert load_config().docling_artifacts_path is None
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", "   ")
    assert load_config().docling_artifacts_path is None


def test_partial_success_parse_json_preserves_stored_warning_prose(monkeypatch, tmp_path):
    from lab import chunking, parse_pipeline
    from lab.docling_pipeline import ImageAsset, ParseArtifacts
    from lab.storage import Store

    parsed = ParseArtifacts(
        markdown="# Title",
        docling={"name": "sample"},
        images=[],
        warnings=[PARTIAL_SUCCESS_WARNING],
        parser_version="2.127.0",
        document=SimpleNamespace(pages={1: None}),
    )
    monkeypatch.setattr(parse_pipeline, "parse_pdf_bytes", lambda *args, **kwargs: parsed)
    monkeypatch.setattr(
        parse_pipeline, "chunk_tokenizer", lambda model, **kwargs: (SimpleNamespace(count_tokens=len), [])
    )
    monkeypatch.setattr(
        parse_pipeline,
        "chunk_docling_document",
        lambda *args, **kwargs: (
            [
                {
                    "index": 0,
                    "text": "body",
                    "contextualized_text": "body",
                    "headings": [],
                    "pages": [1],
                    "bboxes": [],
                    "picture_asset_ids": [],
                }
            ],
            [],
        ),
    )
    store = Store(tmp_path / "topics", tmp_path / "settings.json")
    topic = store.create("Partial")["id"]
    updates, _ = parse_pipeline.parse_and_persist(
        store,
        topic,
        data=b"%PDF-1.7 fixture",
        filename="paper.pdf",
        original_name="2026_09_30_paper.pdf",
        file_id="file1",
    )
    manifest = json.loads((store.file_path(topic, updates["parse_name"])).read_text())
    assert manifest["warnings"][0] == "Docling reported partial_success."
    assert (
        parse_pipeline._extraction_diagnostics(["partial_success"], manifest["warnings"])["status"]
        == "suspected_limitation"
    )
    legacy = parse_pipeline._extraction_diagnostics([], ["Docling reported partial_success."])
    assert legacy["status"] == "suspected_limitation"


def test_two_apps_use_distinct_ollama_base_urls(tmp_path):
    root_a = tmp_path / "a" / "Learning"
    root_b = tmp_path / "b" / "Learning"
    settings_a = tmp_path / "a" / "settings.json"
    settings_b = tmp_path / "b" / "settings.json"
    settings_a.parent.mkdir(parents=True)
    settings_b.parent.mkdir(parents=True)
    settings_a.write_text("{}")
    settings_b.write_text("{}")
    app_a = create_app(root_a, settings_a, config=load_config(ollama_base_url="http://ollama-a:11434"))
    app_b = create_app(root_b, settings_b, config=load_config(ollama_base_url="http://ollama-b:11434"))
    assert isinstance(app_a.state.deps.model_backend, OllamaGateway)
    assert isinstance(app_b.state.deps.model_backend, OllamaGateway)
    assert app_a.state.deps.model_backend._base_url == "http://ollama-a:11434"
    assert app_b.state.deps.model_backend._base_url == "http://ollama-b:11434"


def test_sqlite_index_failure_records_warning_not_500(tmp_path, monkeypatch):
    async def fail_index(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    import lab.web.files as files_module

    monkeypatch.setattr(files_module, "index_chunks", fail_index)

    def fake_structured(*args, **kwargs):
        return (
            {
                "markdown_name": "2026_09_30_paper.md",
                "docling_name": "2026_09_30_paper.docling.json",
                "chunks_name": "2026_09_30_paper.chunks.jsonl",
                "parse_name": "2026_09_30_paper.parse.json",
                "page_count": 1,
                "warnings": [],
                "extraction_diagnostics": {"status": "unassessed", "note": "", "findings": []},
            },
            [
                {
                    "chunk_id": "f:000",
                    "file_id": "f",
                    "file_name": "paper.pdf",
                    "chunk_index": 0,
                    "text": "body",
                    "headings": [],
                    "pages": [1],
                    "bboxes": [],
                    "asset_ids": [],
                    "content_hash": "abc",
                }
            ],
        )

    client = TestClient(
        create_app(tmp_path / "Learning", tmp_path / "settings.json", structured_parser=fake_structured)
    )
    topic = client.post("/api/topics", json={"name": "Index"}).json()["id"]
    response = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"parser": "docling"},
    )
    assert response.status_code == 201
    record = response.json()
    assert record["index_status"] == "error"
    assert "indexing failed" in record["warnings"][-1]


def test_unusual_parser_exception_becomes_conversion_error(tmp_path, monkeypatch):
    class OddFailure(Exception):
        pass

    def explode(*args, **kwargs):
        raise OddFailure("layout blew up")

    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "settings.json",
            parser_map={"markitdown": explode, "anydoc": explode},
        )
    )
    topic = client.post("/api/topics", json={"name": "Parser"}).json()["id"]
    response = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"parser": "markitdown"},
    )
    assert response.status_code == 201
    record = response.json()
    assert record["status"] == "error"
    assert record["error"] == "Conversion failed (OddFailure); check the PDF or use local OCR for scanned pages."


def test_domain_error_mid_stream_yields_error_and_releases_lock(tmp_path, monkeypatch):
    class CorruptStore:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def save_session(self, topic, session):
            if session.get("messages") and session["messages"][-1].get("role") == "assistant":
                raise CorruptData("Session file is corrupt.")
            return self.inner.save_session(topic, session)

    root = tmp_path / "Learning"
    settings = tmp_path / "settings.json"
    app = create_app(root, settings, model_backend=FakeModel())
    app.state.deps.store = CorruptStore(app.state.deps.store)
    client = TestClient(app)
    topic = client.post("/api/topics", json={"name": "Chat"}).json()["id"]
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "hello", "model": "fake", "think": False},
    )
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[-1]["type"] == "error"
    assert "Chat failed" in events[-1]["message"]
    assert not app.state.deps.locks[topic].locked()


def test_tags_http_error_preserves_ollama_chat_failed_message():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            raise httpx.ConnectError("offline", request=request)
        raise AssertionError(request.url.path)

    gateway = OllamaGateway("http://test")
    with patch.object(
        OllamaGateway,
        "_client",
        lambda self: httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handle)),
    ):
        events = asyncio.run(_collect(gateway))

    assert events[-1]["type"] == "error"
    assert events[-1]["message"].startswith("Ollama chat failed:")
    assert "offline" in events[-1]["message"]


async def _collect(gateway: OllamaGateway):
    return [
        event
        async for event in gateway.stream_chat(
            [{"role": "user", "content": "Hi"}],
            "qwen3.5:4b-q8_0",
            generation_lock=asyncio.Lock(),
        )
    ]


def test_import_asgi_does_not_construct_app(monkeypatch):
    monkeypatch.delenv("LEARNING_LAB_ROOT", raising=False)
    sys.modules.pop("lab.asgi", None)
    module = importlib.import_module("lab.asgi")
    assert not hasattr(module, "app")
    assert callable(module.create_app_factory)


def test_done_context_matches_86602ad_algorithm_for_trimmed_prompt():
    messages = [
        {"role": "system", "content": "Rules"},
        {"role": "user", "content": "old" * 300},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "recent"},
        {"role": "user", "content": "latest question"},
    ]
    trimmed, route_context, _reserve, _ = prepare_context_details(messages, 1024)
    legacy_prompt, legacy_context, legacy_prediction = prepare_context(messages, 1024)
    legacy_context = {**legacy_context, "truncated_messages": route_context["truncated_messages"]}

    class Chunks(httpx.AsyncByteStream):
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        async def __aiter__(self):
            yield self.payload

    parts = b'{"done":true,"prompt_eval_count":30,"eval_count":9}\n'
    gateway = OllamaGateway("http://test")

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b-q8_0"}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        return httpx.Response(200, stream=Chunks(parts))

    with patch.object(
        OllamaGateway,
        "_client",
        lambda self: httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handle)),
    ):
        events = asyncio.run(
            _collect_trimmed(gateway, trimmed, route_context),
        )
    assert events[-1]["type"] == "done"
    expected = {**legacy_context, "used": 39, "estimated": False}
    assert events[-1]["context"] == expected
    assert legacy_prediction == 256


async def _collect_trimmed(gateway: OllamaGateway, trimmed, route_context):
    return [
        event
        async for event in gateway.stream_chat(
            trimmed,
            "qwen3.5:4b-q8_0",
            context_limit=1024,
            context_metadata=route_context,
            generation_lock=asyncio.Lock(),
        )
    ]


def test_models_list_survives_connect_error():
    gateway = OllamaGateway("http://offline")

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with patch.object(
        OllamaGateway,
        "_client",
        lambda self: httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(fail)),
    ):
        result = asyncio.run(gateway.list_models())
    assert result["models"] == []
    assert "error" in result
