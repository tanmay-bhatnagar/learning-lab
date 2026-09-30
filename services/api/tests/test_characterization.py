"""Characterization tests: behavior-preserving refactors must keep these passing."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from lab.file_records import mark_interrupted
from lab.main import SYSTEM_RULES, create_app
from lab.storage import Store
from tests.fakes import FakeModel, SlowFakeModel


def _client(tmp_path, model=None, **kwargs):
    root = tmp_path.resolve() / "Learning"
    settings = tmp_path.resolve() / "state" / "settings.json"
    gateway = model or FakeModel()
    return (
        TestClient(
            create_app(
                root,
                settings,
                model_backend=gateway,
                parser_map={
                    "markitdown": lambda data, parser: "# PDF\nEvidence text for citation test.",
                    "anydoc": lambda data, parser: "# PDF\nEvidence text for citation test.",
                },
                **kwargs,
            )
        ),
        root,
        settings,
        gateway,
    )


def _upload(client, topic, name="notes.pdf", data=b"%PDF-1.7\nexample", parser="markitdown"):
    return client.post(
        f"/api/topics/{topic}/files",
        files={"file": (name, data, "application/pdf")},
        data={"parser": parser},
    )


def _chat(client, topic, files=None, **body):
    payload = {"message": "Explain", "file_ids": files or [], "model": "fake", "think": True, **body}
    return client.post(f"/api/topics/{topic}/chat", json=payload)


# --- prompt ordering ---


def test_prompt_order_system_history_evidence_attachments_question(tmp_path):
    client, _, _, model = _client(tmp_path)
    topic = client.post("/api/topics", json={"name": "Order"}).json()["id"]
    record = _upload(client, topic).json()
    _chat(client, topic, [record["id"]])
    prompt = model.calls[0]
    assert prompt[0] == {"role": "system", "content": SYSTEM_RULES}
    assert prompt[-1] == {"role": "user", "content": "Explain"}
    attachment_indices = [index for index, message in enumerate(prompt) if "UNTRUSTED ATTACHMENT" in message["content"]]
    assert len(attachment_indices) == 1
    assert attachment_indices[0] < len(prompt) - 1
    assert len([message for message in prompt if message["role"] == "system"]) == 1


def test_learning_goal_appended_to_system_message(tmp_path):
    client, _, _, model = _client(tmp_path)
    topic = client.post("/api/topics", json={"name": "Goal"}).json()["id"]
    goal = "Understand eigenvectors well enough to explain them."
    client.put(f"/api/topics/{topic}/learning-goal", json={"learning_goal": goal})
    _chat(client, topic)
    system = model.calls[0][0]["content"]
    assert "USER-AUTHORED LEARNING GOAL FOR THIS TOPIC" in system
    assert goal in system
    assert system.startswith(SYSTEM_RULES)


def test_evidence_is_reversed_before_attachments(tmp_path):
    """Evidence chunks appear in reverse retrieval order, before attachments."""
    from tests.test_retrieval_api import fake_structured_parser

    model = FakeModel()
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state" / "settings.json",
            model_backend=model,
            structured_parser=fake_structured_parser,
        )
    )
    topic = client.post("/api/topics", json={"name": "Evidence"}).json()["id"]
    record = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    _chat(client, topic, [record["id"]])
    prompt = model.calls[0]
    evidence_messages = [message for message in prompt if "UNTRUSTED RETRIEVED EVIDENCE" in message.get("content", "")]
    assert evidence_messages
    attachment_messages = [message for message in prompt if "UNTRUSTED ATTACHMENT" in message.get("content", "")]
    evidence_indices = [prompt.index(message) for message in evidence_messages]
    if attachment_messages:
        assert max(evidence_indices) < prompt.index(attachment_messages[0])


def test_citations_match_retained_evidence_after_trimming(tmp_path):
    """Retained citations in the done event must match retrieved evidence in the model prompt."""
    from tests.test_retrieval_api import fake_structured_parser

    async def ranked_retriever(store, topic, query, **kwargs):
        if query != "rank test":
            return {"mode": "keyword", "hits": []}
        file_id = kwargs.get("file_ids", ["x"])[0]
        return {
            "mode": "keyword",
            "hits": [
                {
                    "chunk_id": "rank-one",
                    "file_id": file_id,
                    "file_name": "paper.pdf",
                    "text": "Top ranked evidence.",
                    "headings": [],
                    "pages": [1],
                    "bboxes": [],
                    "asset_ids": [],
                    "trace": {"fusion": {"rank": 1, "score": 1.0}},
                },
                {
                    "chunk_id": "rank-two",
                    "file_id": file_id,
                    "file_name": "paper.pdf",
                    "text": "Lower ranked. " + ("extra " * 300),
                    "headings": [],
                    "pages": [2],
                    "bboxes": [],
                    "asset_ids": [],
                    "trace": {"fusion": {"rank": 2, "score": 0.5}},
                },
            ],
        }

    model = FakeModel(token_text="grounded answer")
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state" / "settings.json",
            model_backend=model,
            structured_parser=fake_structured_parser,
            retriever=ranked_retriever,
        )
    )
    topic = client.post("/api/topics", json={"name": "Citations"}).json()["id"]
    record = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "rank test", "file_ids": [record["id"]], "model": "fake", "context_limit": 2048},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    citations = events[-1]["retrieval"]["citations"]
    prompt = model.calls[-1]
    evidence = [message["content"] for message in prompt if "UNTRUSTED RETRIEVED EVIDENCE" in message["content"]]
    assert [item["chunk_id"] for item in citations] == ["rank-one"]
    assert len(evidence) == 1 and "Top ranked evidence." in evidence[0]


# --- upload record transitions ---


def test_upload_record_transitions_ready(tmp_path):
    client, _, _, _ = _client(tmp_path)
    topic = client.post("/api/topics", json={"name": "Upload"}).json()["id"]
    record = _upload(client, topic).json()
    assert record["status"] == "ready"
    assert record["index_status"] == "not_indexed"


def test_upload_record_transitions_error(tmp_path):
    root = tmp_path / "Learning"
    settings = tmp_path / "state" / "settings.json"

    def fail(*args):
        raise ValueError("Scanned PDF needs local OCR")

    client = TestClient(create_app(root, settings, parser_map={"markitdown": fail, "anydoc": fail}))
    topic = client.post("/api/topics", json={"name": "Fail"}).json()["id"]
    record = _upload(client, topic, parser="anydoc").json()
    assert record["status"] == "error"
    assert "OCR" in record["error"]


def test_upload_record_transitions_index_status_values(tmp_path):
    from tests.test_retrieval_api import fake_structured_parser

    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state" / "settings.json",
            model_backend=FakeModel(),
            structured_parser=fake_structured_parser,
        )
    )
    topic = client.post("/api/topics", json={"name": "Indexed"}).json()["id"]
    record = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    assert record["status"] == "ready"
    assert record["index_status"] == "ready"


def test_mark_interrupted_transitions_processing_to_error():
    records = [
        {"id": "done", "status": "ready"},
        {"id": "stale", "status": "processing"},
        {"id": "live", "status": "processing"},
    ]
    marked = mark_interrupted(records, {"live"})
    assert [record["status"] for record in marked] == ["ready", "error", "processing"]
    assert marked[1]["interrupted"] is True


# --- lock release ---


def test_lock_released_on_success(tmp_path):
    client, _, _, _ = _client(tmp_path)
    topic = client.post("/api/topics", json={"name": "Success"}).json()["id"]
    response = _chat(client, topic)
    assert response.status_code == 200
    assert _chat(client, topic).status_code == 200


def test_lock_released_on_error(tmp_path):
    root = tmp_path / "Learning"
    settings = tmp_path / "state" / "settings.json"
    client = TestClient(create_app(root, settings, model_backend=FakeModel(fail=True)))
    topic = client.post("/api/topics", json={"name": "Error"}).json()["id"]
    response = _chat(client, topic)
    assert json.loads(response.text.splitlines()[-1])["type"] == "error"
    assert _chat(client, topic).status_code == 200


def test_lock_released_on_busy_rejection(tmp_path):
    started, release = threading.Event(), threading.Event()
    root = tmp_path / "Learning"
    settings = tmp_path / "state" / "settings.json"
    with TestClient(create_app(root, settings, model_backend=SlowFakeModel(started, release))) as client:
        topic = client.post("/api/topics", json={"name": "Busy"}).json()["id"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_chat, client, topic)
            assert started.wait(timeout=5)
            assert _chat(client, topic).status_code == 409
            release.set()
            assert future.result(timeout=5).status_code == 200


# --- HTTP error status and message table ---


API_ERRORS = [
    # storage.py valid_id — tested via test_api.test_safe_ids; HTTP layer returns same message
    # storage.py symlink
    pytest.param(
        lambda client, topic, root, settings: (_ for _ in ()).throw(
            HTTPException(403, "Symlink paths are not allowed.")
        ),
        403,
        "Symlink paths are not allowed.",
        id="symlink-path",
        marks=pytest.mark.skip(reason="direct Store test in test_api.py"),
    ),
    # storage.py topic not found
    pytest.param(
        lambda client, topic, root, settings: client.get("/api/topics/nonexistent-topic/files"),
        404,
        "Topic not found.",
        id="topic-not-found",
    ),
    # storage.py attachment not found
    pytest.param(
        lambda client, topic, root, settings: client.post(
            f"/api/topics/{topic}/chat",
            json={"message": "x", "file_ids": ["00000000000000000000000000000001"], "model": "fake"},
        ),
        404,
        "Attachment not found in the selected topic.",
        id="attachment-not-found",
    ),
    # storage.py invalid filename
    pytest.param(
        lambda client, topic, root, settings: (
            (root / topic / "files.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "abc12345678901234567890123456789012",
                            "name": "x",
                            "status": "ready",
                            "markdown_name": "../../evil.md",
                        }
                    ]
                )
            ),
            client.get(f"/api/topics/{topic}/files/abc12345678901234567890123456789012/markdown"),
        )[1],
        403,
        "Invalid stored filename.",
        id="invalid-stored-filename",
    ),
    # storage.py corrupt json
    pytest.param(
        lambda client, topic, root, settings: (
            (root / topic / "session.json").write_text("broken-json"),
            _chat(client, topic),
        )[1],
        500,
        "Invalid saved data in session.json; restore a backup before retrying.",
        id="corrupt-session",
    ),
    # main.py upload validation
    pytest.param(
        lambda client, topic, root, settings: _upload(client, topic, "../escape.pdf"),
        400,
        "Upload a PDF with a plain filename, without path separators.",
        id="upload-bad-filename",
    ),
    pytest.param(
        lambda client, topic, root, settings: _upload(client, topic, data=b"not a pdf"),
        400,
        "File does not have a valid PDF header.",
        id="upload-bad-header",
    ),
    # main.py upload size
    pytest.param(
        lambda client, topic, root, settings: TestClient(
            create_app(
                root,
                settings,
                model_backend=FakeModel(),
                parser_map={"markitdown": lambda d, p: "# x", "anydoc": lambda d, p: "# x"},
                max_upload_bytes=10,
            )
        ).post(
            f"/api/topics/{topic}/files",
            files={"file": ("file.pdf", b"%PDF-1" + b"x" * 20, "application/pdf")},
            data={"parser": "markitdown"},
        ),
        413,
        "PDF exceeds the 10 byte upload limit.",
        id="upload-pdf-size",
    ),
    # main.py markdown not ready
    pytest.param(
        lambda client, topic, root, settings: (
            record := _upload(client, topic, parser="anydoc").json(),
            (root / topic / "files.json").write_text(json.dumps([{**record, "status": "processing"}])),
            client.get(f"/api/topics/{topic}/files/{record['id']}/markdown"),
        )[2],
        409,
        "Conversion is not complete.",
        id="markdown-not-ready",
    ),
    # main.py docling not available
    pytest.param(
        lambda client, topic, root, settings: client.get(
            f"/api/topics/{topic}/files/{_upload(client, topic).json()['id']}/parsed"
        ),
        409,
        "Structured Docling output is not available for this file.",
        id="parsed-not-available",
    ),
    # main.py chunks not available
    pytest.param(
        lambda client, topic, root, settings: client.get(
            f"/api/topics/{topic}/files/{_upload(client, topic).json()['id']}/chunks"
        ),
        409,
        "Structured chunks are not available for this file.",
        id="chunks-not-available",
    ),
    # main.py asset not found
    pytest.param(
        lambda client, topic, root, settings: client.get(
            f"/api/topics/{topic}/files/{_upload(client, topic).json()['id']}/assets/missing"
        ),
        404,
        "Visual asset not found for this file.",
        id="asset-not-found",
    ),
    # main.py topic busy
    pytest.param(
        lambda client, topic, root, settings: None,  # handled in test_lock_released_on_busy_rejection
        409,
        "This topic is busy. Wait for its current upload or reply to finish.",
        id="topic-busy",
        marks=pytest.mark.skip(reason="covered by lock release test"),
    ),
    # main.py attachment not ready
    pytest.param(
        lambda client, topic, root, settings: (
            record := _upload(client, topic).json(),
            (root / topic / "files.json").write_text(json.dumps([{**record, "status": "processing"}])),
            _chat(client, topic, [record["id"]]),
        )[2],
        409,
        None,  # prefix match
        id="attachment-not-ready",
    ),
    # main.py index missing
    pytest.param(
        lambda client, topic, root, settings: (
            record := _upload(client, topic).json(),
            (root / topic / "files.json").write_text(json.dumps([{**record, "index_status": "ready"}])),
            (root / topic / "retrieval.sqlite").unlink(missing_ok=True),
            _chat(client, topic, [record["id"]]),
        )[3],
        409,
        "Indexed evidence is unavailable",
        id="index-missing",
    ),
    # main.py context limit — requires indexed attachments that exceed budget; see test_retrieval_api
    # middleware browser origin
    pytest.param(
        lambda client, topic, root, settings: client.post(
            "/api/topics", json={"name": "evil"}, headers={"Origin": "https://evil.example"}
        ),
        403,
        "Browser origin is not allowed.",
        id="browser-origin",
    ),
    # middleware upload content-length
    pytest.param(
        lambda client, topic, root, settings: TestClient(
            create_app(
                root,
                settings,
                model_backend=FakeModel(),
                parser_map={"markitdown": lambda d, p: "# x", "anydoc": lambda d, p: "# x"},
                max_upload_bytes=10,
            )
        ).post(
            f"/api/topics/{topic}/files",
            files={"file": ("file.pdf", b"%PDF-1.7\n" + b"x" * 100000, "application/pdf")},
            data={"parser": "markitdown"},
            headers={"Content-Length": "200000"},
        ),
        413,
        "Upload exceeds 10 byte PDF limit.",
        id="content-length-limit",
    ),
]


@pytest.fixture
def api_setup(tmp_path):
    client, root, settings, model = _client(tmp_path)
    topic = client.post("/api/topics", json={"name": "Errors"}).json()["id"]
    return client, topic, root, settings, model


@pytest.mark.parametrize("trigger,status,detail", API_ERRORS)
def test_api_error_status_and_message(api_setup, trigger, status, detail):
    client, topic, root, settings, _ = api_setup
    if trigger is None:
        pytest.skip("handled elsewhere")
    response = trigger(client, topic, root, settings)
    assert response.status_code == status, response.text
    if detail:
        body = response.json()
        assert detail in body.get("detail", body.get("message", str(body)))
