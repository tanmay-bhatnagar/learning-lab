"""Round-3 audit regressions: reporting boundaries keep the original degrade-not-fail outcomes."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from lab.web.app import create_app
from tests.fakes import FakeModel, UnavailableEmbedFakeModel
from tests.test_retrieval_api import fake_structured_parser


class OddFailure(Exception):
    pass


def test_unusual_index_exception_keeps_document_ready_with_warning(tmp_path, monkeypatch):
    async def fail_index(*args, **kwargs):
        raise OddFailure("vector store blew up")

    import lab.web.files as files_module

    monkeypatch.setattr(files_module, "index_chunks", fail_index)
    client = TestClient(
        create_app(tmp_path / "Learning", tmp_path / "settings.json", structured_parser=fake_structured_parser)
    )
    topic = client.post("/api/topics", json={"name": "Index"}).json()["id"]
    response = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"parser": "docling"},
    )
    assert response.status_code == 201
    record = response.json()
    assert record["status"] == "ready"
    assert record["index_status"] == "error"
    assert record["warnings"][-1] == "Document parsed, but indexing failed (OddFailure): vector store blew up"


class BrokenListModel(FakeModel):
    async def list_models(self) -> dict:
        raise OddFailure("malformed model metadata")


def test_models_route_reports_any_backend_failure_as_payload(tmp_path):
    client = TestClient(create_app(tmp_path / "Learning", tmp_path / "settings.json", model_backend=BrokenListModel()))
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json() == {
        "models": [],
        "error": "Model service unavailable (OddFailure); check the local model service and backend dependencies.",
    }


class BrokenListEmbedModel(UnavailableEmbedFakeModel):
    async def list_models(self) -> dict:
        raise OddFailure("malformed model metadata")


def test_chat_vision_probe_failure_falls_back_to_text_evidence(tmp_path):
    model = BrokenListEmbedModel(token_text="grounded answer")
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "settings.json",
            model_backend=model,
            structured_parser=fake_structured_parser,
        )
    )
    topic = client.post("/api/topics", json={"name": "Vision"}).json()["id"]
    record = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "What is the calibration value?", "file_ids": [record["id"]], "model": "fake"},
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done"
    assert events[-1]["retrieval"]["citations"][0]["pages"] == [1]
    assert not any(message.get("images") for message in model.calls[0])
