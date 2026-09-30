import json

from fastapi.testclient import TestClient

import lab.main as main_module
from lab import models
from lab.main import create_app
from lab.storage import write_json, write_text


class FakeModel:
    def __init__(self):
        self.calls = []

    async def list_models(self):
        return {"models": [{"id": "fake", "vision": False}]}

    async def stream_chat(self, messages, model, think, context_limit):
        self.calls.append(messages)
        yield {"type": "token", "text": "grounded answer"}
        yield {
            "type": "done",
            "model": model,
            "context": {"used": 10, "limit": context_limit, "estimated": True, "truncated_messages": 0},
        }


def fake_structured_parser(store, topic, *, data, filename, original_name, file_id, embedding_model=""):
    base = original_name[:-4]
    markdown_name = base + ".md"
    docling_name = base + ".docling.json"
    chunks_name = base + ".chunks.jsonl"
    parse_name = base + ".parse.json"
    write_text(
        store.file_path(topic, markdown_name),
        "# Calibration\n\nThe calibration value is exactly 42.\n\nUNRELATED FULL DOCUMENT TAIL",
    )
    write_json(store.file_path(topic, docling_name), {"name": filename, "texts": []})
    write_text(
        store.file_path(topic, chunks_name),
        json.dumps(
            {
                "chunk_id": f"{file_id}:text:000000",
                "contextualized_text": "Calibration\nThe calibration value is exactly 42.",
            }
        )
        + "\n",
    )
    write_json(store.file_path(topic, parse_name), {"parser": "docling"})
    chunks = [
        {
            "chunk_id": f"{file_id}:text:000000",
            "file_id": file_id,
            "file_name": filename,
            "chunk_index": 0,
            "text": "Calibration\nThe calibration value is exactly 42.",
            "headings": ["Calibration"],
            "pages": [1],
            "bboxes": [],
            "asset_ids": [],
            "content_hash": "hash",
        }
    ]
    return {
        "markdown_name": markdown_name,
        "docling_name": docling_name,
        "chunks_name": chunks_name,
        "parse_name": parse_name,
        "content_sha256": "source-hash",
        "parser_version": "test",
        "page_count": 1,
        "asset_count": 0,
        "assets": [],
        "warnings": [],
    }, chunks


def test_docling_upload_indexes_and_chat_retrieves_bounded_evidence(tmp_path):
    root = tmp_path / "Learning"
    settings = tmp_path / "state" / "settings.json"
    model = FakeModel()
    client = TestClient(
        create_app(
            root,
            settings,
            model_backend=model,
            structured_parser=fake_structured_parser,
        )
    )
    topic = client.post("/api/topics", json={"name": "Retrieval"}).json()["id"]
    upload = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    )
    assert upload.status_code == 201
    record = upload.json()
    assert record["status"] == "ready"
    assert record["index_status"] == "ready"
    assert record["index_mode"] == "keyword"
    assert (root / topic / "retrieval.sqlite").exists()

    trace = client.post(
        f"/api/topics/{topic}/retrieval/trace",
        json={"query": "calibration", "file_ids": [record["id"]]},
    ).json()
    assert trace["mode"] == "keyword"
    assert trace["hits"][0]["pages"] == [1]

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "What is the calibration value?", "file_ids": [record["id"]], "model": "fake"},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["retrieval"]["citations"][0]["pages"] == [1]
    prompt = model.calls[0]
    evidence = [message["content"] for message in prompt if "UNTRUSTED RETRIEVED EVIDENCE" in message["content"]]
    assert evidence and "exactly 42" in evidence[0]
    assert not any("UNRELATED FULL DOCUMENT TAIL" in message["content"] for message in prompt)

    no_selection = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "calibration", "file_ids": [], "model": "fake"},
    )
    assert no_selection.status_code == 200
    assert not any("UNTRUSTED RETRIEVED EVIDENCE" in message["content"] for message in model.calls[-1])

    fallback = client.post(
        f"/api/topics/{topic}/retrieval/trace",
        json={"query": "!!!", "file_ids": [record["id"]]},
    ).json()
    assert fallback["mode"] == "fallback"
    assert len(fallback["hits"]) == 1
    assert "bounded opening chunks" in fallback["warning"]


def test_chat_citations_follow_real_model_context_trimming_with_legacy_attachment(tmp_path, monkeypatch):
    import httpx
    from unittest.mock import patch

    payloads = []

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fake"}, {"name": "nomic-embed-text"}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        if request.url.path == "/api/chat":
            payloads.append(json.loads(request.content))
            return httpx.Response(
                200, content=(b'{"message":{"content":"ok"},"done":true,"prompt_eval_count":10,"eval_count":2}\n')
            )
        if request.url.path == "/api/embed":
            return httpx.Response(503, json={"error": "embedding service unavailable"})
        raise AssertionError(request.url.path)

    client_factory = patch.object(
        models, "_client", lambda: httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handle))
    )
    client_factory.start()

    async def fixed_retriever(store, topic, query, **kwargs):
        if query == "rank test":
            return {
                "mode": "keyword",
                "hits": [
                    {
                        "chunk_id": "rank-one",
                        "file_id": indexed["id"],
                        "file_name": "indexed.pdf",
                        "text": "Top ranked evidence.",
                        "headings": ["Top"],
                        "pages": [1],
                        "bboxes": [],
                        "asset_ids": [],
                        "trace": {"fusion": {"rank": 1, "score": 1.0}},
                    },
                    {
                        "chunk_id": "rank-two",
                        "file_id": indexed["id"],
                        "file_name": "indexed.pdf",
                        "text": "Lower ranked. " + ("extra " * 300),
                        "headings": ["Lower"],
                        "pages": [2],
                        "bboxes": [],
                        "asset_ids": [],
                        "trace": {"fusion": {"rank": 2, "score": 0.5}},
                    },
                ],
            }
        return {
            "mode": "keyword",
            "hits": [
                {
                    "chunk_id": f"{indexed['id']}:text:000000",
                    "file_id": indexed["id"],
                    "file_name": "indexed.pdf",
                    "text": "The calibration value is exactly 42.",
                    "headings": ["Calibration"],
                    "pages": [1],
                    "bboxes": [],
                    "asset_ids": [],
                    "trace": {"fusion": {"rank": 1, "score": 1.0}},
                }
            ],
        }

    try:
        monkeypatch.setattr(
            main_module, "convert_pdf", lambda data, parser: "Legacy attachment text. " + ("extra " * 50)
        )
        root = tmp_path / "Learning"
        client = TestClient(
            create_app(
                root,
                tmp_path / "state/settings.json",
                structured_parser=fake_structured_parser,
                retriever=fixed_retriever,
            )
        )
        topic = client.post("/api/topics", json={"name": "Trim citations"}).json()["id"]
        indexed = client.post(
            f"/api/topics/{topic}/files",
            files={"file": ("indexed.pdf", b"%PDF-1.7\nexample", "application/pdf")},
            data={"parser": "docling"},
        ).json()
        legacy = client.post(
            f"/api/topics/{topic}/files",
            files={"file": ("legacy.pdf", b"%PDF-1.7\nexample", "application/pdf")},
            data={"parser": "markitdown"},
        ).json()
        files = [indexed["id"], legacy["id"]]
        assert indexed["index_status"] == "ready"
        assert (root / topic / "retrieval.sqlite").exists()

        full_message = "Question with complete durable content."
        tight = client.post(
            f"/api/topics/{topic}/chat",
            json={
                "message": full_message,
                "file_ids": files,
                "model": "fake",
                "context_limit": 1536,
            },
        )
        tight_events = [json.loads(line) for line in tight.text.splitlines()]
        assert tight_events[-1]["type"] == "done"
        assert tight_events[-1]["context"]["truncated_messages"] > 0
        assert tight_events[-1]["retrieval"]["citations"] == []
        assert not any("UNTRUSTED RETRIEVED EVIDENCE" in m["content"] for m in payloads[-1]["messages"])

        ranked = client.post(
            f"/api/topics/{topic}/chat",
            json={
                "message": "rank test",
                "file_ids": files,
                "model": "fake",
                "context_limit": 2048,
            },
        )
        ranked_events = [json.loads(line) for line in ranked.text.splitlines()]
        ranked_citations = ranked_events[-1]["retrieval"]["citations"]
        assert [item["chunk_id"] for item in ranked_citations] == ["rank-one"]
        ranked_evidence = [
            m["content"] for m in payloads[-1]["messages"] if "UNTRUSTED RETRIEVED EVIDENCE" in m["content"]
        ]
        assert len(ranked_evidence) == 1 and "Top ranked evidence." in ranked_evidence[0]

        normal = client.post(
            f"/api/topics/{topic}/chat",
            json={
                "message": "What is the calibration value?",
                "file_ids": files,
                "model": "fake",
                "context_limit": 8192,
            },
        )
        normal_events = [json.loads(line) for line in normal.text.splitlines()]
        assert normal_events[-1]["type"] == "done"
        citations = normal_events[-1]["retrieval"]["citations"]
        assert citations and all(item["file_id"] == indexed["id"] for item in citations)
        assert any("Legacy attachment text." in m["content"] for m in payloads[-1]["messages"])
        saved = client.get(f"/api/topics/{topic}/messages").json()["messages"]
        assert saved[-6]["content"] == full_message
        assert saved[-1]["retrieval"]["citations"] == citations
        assert saved[-5]["retrieval"]["citations"] == []
        assert [item["chunk_id"] for item in saved[-3]["retrieval"]["citations"]] == ["rank-one"]
    finally:
        client_factory.stop()


def test_missing_embedding_model_degrades_upload_trace_and_chat_to_keywords(tmp_path):
    import httpx
    from unittest.mock import patch

    installed = [{"name": "fake"}, {"name": "nomic-embed-text"}]

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": installed})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        if request.url.path == "/api/embed":
            count = len(json.loads(request.content)["input"])
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0]] * count})
        if request.url.path == "/api/chat":
            return httpx.Response(
                200, content=(b'{"message":{"content":"ok"},"done":true,"prompt_eval_count":10,"eval_count":2}\n')
            )
        raise AssertionError(request.url.path)

    def upload(client, topic, name):
        return client.post(
            f"/api/topics/{topic}/files",
            files={"file": (name, b"%PDF-1.7\nexample", "application/pdf")},
            data={"parser": "docling"},
        ).json()

    with patch.object(
        models, "_client", lambda: httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handle))
    ):
        client = TestClient(
            create_app(
                tmp_path / "Learning",
                tmp_path / "state/settings.json",
                structured_parser=fake_structured_parser,
            )
        )
        topic = client.post("/api/topics", json={"name": "Embedding offline"}).json()["id"]
        earlier = upload(client, topic, "earlier.pdf")
        assert earlier["index_mode"] == "hybrid"

        installed.pop()
        later = upload(client, topic, "later.pdf")
        assert later["status"] == "ready"
        assert later["index_status"] == "ready"
        assert later["index_mode"] == "keyword"
        assert any("not installed" in warning for warning in later["warnings"])

        trace = client.post(
            f"/api/topics/{topic}/retrieval/trace", json={"query": "calibration", "file_ids": [earlier["id"]]}
        )
        assert trace.status_code == 200
        assert trace.json()["mode"] == "keyword"
        assert "not installed" in trace.json()["warning"]

        response = client.post(
            f"/api/topics/{topic}/chat",
            json={
                "message": "What is the calibration value?",
                "file_ids": [earlier["id"], later["id"]],
                "model": "fake",
            },
        )
        assert response.status_code == 200
        done = json.loads(response.text.splitlines()[-1])
        assert done["type"] == "done"
        assert done["retrieval"]["mode"] == "keyword"
        assert "not installed" in done["retrieval"]["warning"]
        assert {item["file_id"] for item in done["retrieval"]["citations"]} <= {earlier["id"], later["id"]}
        assert done["retrieval"]["citations"]


def test_chat_reports_missing_index_for_selected_ready_indexed_file(tmp_path):
    root = tmp_path / "Learning"
    client = TestClient(
        create_app(
            root,
            tmp_path / "state/settings.json",
            model_backend=FakeModel(),
            structured_parser=fake_structured_parser,
        )
    )
    topic = client.post("/api/topics", json={"name": "Missing index"}).json()["id"]
    record = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    (root / topic / "retrieval.sqlite").unlink()
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "What is in the file?",
            "file_ids": [record["id"]],
            "model": "fake",
        },
    )
    assert response.status_code == 409
    assert "retrieval index is missing" in response.json()["detail"]


def test_chat_budget_error_is_actionable_releases_lock_and_preserves_history(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            model_backend=FakeModel(),
        )
    )
    topic = client.post("/api/topics", json={"name": "Context error"}).json()["id"]
    failed = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Question",
            "file_ids": [],
            "model": "fake",
            "context_limit": 1024,
        },
    )
    assert failed.status_code == 422
    assert "does not fit this context limit" in failed.json()["detail"]
    assert client.get(f"/api/topics/{topic}/messages").json()["messages"] == []

    succeeded = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Question",
            "file_ids": [],
            "model": "fake",
            "context_limit": 4096,
        },
    )
    assert succeeded.status_code == 200
    assert [message["content"] for message in client.get(f"/api/topics/{topic}/messages").json()["messages"]] == [
        "Question",
        "grounded answer",
    ]


def test_trace_rejects_cross_topic_file_scope(tmp_path):
    root = tmp_path / "Learning"
    settings = tmp_path / "state" / "settings.json"
    client = TestClient(
        create_app(
            root,
            settings,
            model_backend=FakeModel(),
            structured_parser=fake_structured_parser,
        )
    )
    first = client.post("/api/topics", json={"name": "First"}).json()["id"]
    second = client.post("/api/topics", json={"name": "Second"}).json()["id"]
    record = client.post(
        f"/api/topics/{first}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    response = client.post(
        f"/api/topics/{second}/retrieval/trace",
        json={"query": "calibration", "file_ids": [record["id"]]},
    )
    assert response.status_code == 404


def _trace():
    return {
        "keyword": {"rank": 1, "score": -1.0},
        "embedding": {"rank": None, "score": None},
        "fusion": {"rank": 1, "score": 0.016},
    }


async def _turn_retriever(store, topic, query, **kwargs):
    turn = len(_turn_retriever.calls)
    _turn_retriever.calls.append(query)
    return {
        "hits": [
            {
                "chunk_id": f"file1:text:{turn:06d}",
                "file_id": "file1",
                "file_name": "paper.pdf",
                "chunk_index": turn,
                "text": f"Evidence for turn {turn}: {query}",
                "headings": [f"Section {turn}"],
                "pages": [turn + 1],
                "bboxes": [],
                "asset_ids": [],
                "trace": _trace(),
            }
        ],
        "mode": "keyword",
    }


_turn_retriever.calls = []


def test_chat_retrieval_persists_per_assistant_message(tmp_path):
    root = tmp_path / "Learning"
    settings = tmp_path / "state" / "settings.json"
    model = FakeModel()
    _turn_retriever.calls = []
    client = TestClient(
        create_app(
            root,
            settings,
            model_backend=model,
            structured_parser=fake_structured_parser,
            retriever=_turn_retriever,
        )
    )
    topic = client.post("/api/topics", json={"name": "Chat retrieval"}).json()["id"]
    record = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()

    first = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "first question", "file_ids": [record["id"]], "model": "fake"},
    )
    first_done = json.loads(first.text.splitlines()[-1])
    assert first_done["retrieval"]["citations"][0]["chunk_index"] == 0
    assert first_done["retrieval"]["citations"][0]["text"].startswith("Evidence for turn 0")

    second = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "second question", "file_ids": [record["id"]], "model": "fake"},
    )
    assert json.loads(second.text.splitlines()[-1])["retrieval"]["citations"][0]["chunk_index"] == 1

    saved = client.get(f"/api/topics/{topic}/messages").json()
    assert saved["messages"][1]["retrieval"]["citations"][0]["chunk_index"] == 0
    assert saved["messages"][3]["retrieval"]["citations"][0]["chunk_index"] == 1
    assert "retrieval" not in saved

    prompt = model.calls[1]
    for message in prompt:
        assert "retrieval" not in message
        assert "citations" not in message


def test_partial_chat_still_attaches_retrieval(tmp_path):
    root = tmp_path / "Learning"
    settings = tmp_path / "state" / "settings.json"
    _turn_retriever.calls = []

    class FailingModel(FakeModel):
        async def stream_chat(self, messages, model, think, context_limit):
            self.calls.append(messages)
            yield {"type": "token", "text": "partial"}
            raise RuntimeError("offline")

    client = TestClient(
        create_app(
            root,
            settings,
            model_backend=FailingModel(),
            structured_parser=fake_structured_parser,
            retriever=_turn_retriever,
        )
    )
    topic = client.post("/api/topics", json={"name": "Partial"}).json()["id"]
    record = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "question", "file_ids": [record["id"]], "model": "fake"},
    )
    assert json.loads(response.text.splitlines()[-1])["type"] == "error"
    assistant = client.get(f"/api/topics/{topic}/messages").json()["messages"][-1]
    assert assistant["content"] == "partial"
    assert assistant["incomplete"] is True
    assert assistant["retrieval"]["citations"][0]["chunk_index"] == 0


def test_index_failure_keeps_successful_docling_artifacts_available(tmp_path, monkeypatch):
    async def fail_index(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(main_module, "index_chunks", fail_index)
    root = tmp_path / "Learning"
    settings = tmp_path / "state" / "settings.json"
    client = TestClient(
        create_app(
            root,
            settings,
            model_backend=FakeModel(),
            structured_parser=fake_structured_parser,
        )
    )
    topic = client.post("/api/topics", json={"name": "Index failure"}).json()["id"]
    response = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    )
    record = response.json()
    assert record["status"] == "ready"
    assert record["index_status"] == "error"
    assert "indexing failed" in record["warnings"][-1]
    assert client.get(f"/api/topics/{topic}/files/{record['id']}/markdown").status_code == 200
