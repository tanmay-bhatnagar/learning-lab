"""Gate 1 workflow characterization through public HTTP NDJSON streams.

Direct-answer token text is asserted as the concatenation of all ``token`` events,
not the number of token events. After LangGraph cutover, large direct answers may
be split into multiple fragments (≤8 KiB each); concatenated text must stay the same.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient

from lab.evidence_turn import _INVALID_OUTPUT, _PROVIDER_ERROR
from lab.prerequisites import MAX_RESPONSE_BYTES
from lab.web.app import create_app
from tests.fakes import FakeModel
from tests.test_document_map_summaries_api import SummaryFakeModel, _client as summary_client_fixture
from tests.test_document_map_summaries_api import _events as summary_events
from tests.test_document_map_summaries_api import _summary_url
from tests.test_evidence_chat import (
    EvidenceModel,
    _app as evidence_app,
    _retriever,
    _search_retriever,
    _structured_parser,
    _topic_with_index,
)
from tests.test_query_traces import payload as chat_payload
from tests.test_web_prerequisites import (
    PrerequisiteFakeModel,
    _events as prerequisite_events,
    _generate_url,
    _prepared,
    _request,
)


def _ndjson_types(response) -> list[str]:
    return [event["type"] for event in _parse_ndjson(response)]


def _parse_ndjson(response) -> list[dict[str, Any]]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def _terminal_message(events: list[dict[str, Any]]) -> str:
    terminal = events[-1]
    assert terminal["type"] == "error"
    message = terminal.get("message")
    assert isinstance(message, str)
    return message


def _concat_tokens(events: list[dict[str, Any]]) -> str:
    return "".join(event.get("text", "") for event in events if event.get("type") == "token")


def _trace(client: TestClient, topic: str, *, conversation_id: str = "default") -> dict[str, Any]:
    traces = client.get(f"/api/topics/{topic}/query-traces").json()["traces"]
    scoped = [item for item in traces if item.get("conversation_id") == conversation_id]
    assert len(scoped) == 1
    return scoped[0]


class _ProviderErrorEventModel(FakeModel):
    """Yields a provider ``error`` event after partial output (ordinary chat path)."""

    def __init__(self, *, message: str = "synthetic mid-stream provider error"):
        super().__init__(token_text="partial")
        self.provider_message = message

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        think: bool | str | None,
        context_limit: int,
        context_metadata: dict | None = None,
        *,
        generation_lock: asyncio.Lock,
    ) -> AsyncIterator[dict]:
        self.calls.append(messages)
        async with generation_lock:
            yield {"type": "thinking", "text": "reasoning"}
            yield {"type": "token", "text": self.token_text}
            yield {"type": "error", "message": self.provider_message}


class _PrematureEofModel(FakeModel):
    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        think: bool | str | None,
        context_limit: int,
        context_metadata: dict | None = None,
        *,
        generation_lock: asyncio.Lock,
    ) -> AsyncIterator[dict]:
        self.calls.append(messages)
        async with generation_lock:
            yield {"type": "thinking", "text": "reasoning"}
            yield {"type": "token", "text": "partial without done"}


class _DecisionStreamModel(EvidenceModel):
    """Controls the structured decision stream separately from the final prose stream."""

    def __init__(self, decision_behavior: str, *, final_actions: list[str] | None = None):
        super().__init__(final_actions or [])
        self.decision_behavior = decision_behavior

    def stream_chat(
        self,
        messages,
        model,
        think=None,
        context_limit=8192,
        context_metadata=None,
        *,
        generation_lock,
        response_schema=None,
    ):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "response_schema": response_schema,
            }
        )

        async def decision_stream():
            async with generation_lock:
                if self.decision_behavior == "provider_error":
                    yield {"type": "error", "message": "decision provider fault"}
                    return
                if self.decision_behavior == "incomplete":
                    yield {"type": "token", "text": '{"action":'}
                    return
                raise AssertionError(f"unexpected decision behavior: {self.decision_behavior}")

        async def ordinary_stream():
            async with generation_lock:
                yield {"type": "token", "text": "Grounded answer."}
                yield {
                    "type": "done",
                    "model": model,
                    "context": {"used": 77, "limit": context_limit, "estimated": False},
                }

        if response_schema is not None:
            return decision_stream()
        return ordinary_stream()


class _RevisionChangeSummaryModel(SummaryFakeModel):
    def __init__(self, store, topic: str):
        super().__init__()
        self._store = store
        self._topic = topic

    def stream_chat(
        self,
        messages: list[dict],
        model: str,
        think: bool | str | None,
        context_limit: int,
        context_metadata: dict | None = None,
        *,
        generation_lock: asyncio.Lock,
    ) -> AsyncIterator[dict]:
        self.summary_requests.append(
            {
                "messages": messages,
                "model": model,
                "think": think,
                "context_limit": context_limit,
                "context_metadata": context_metadata,
                "generation_lock": generation_lock,
            }
        )

        async def events() -> AsyncIterator[dict]:
            async with generation_lock:
                yield {"type": "thinking", "text": "checking sources"}
                yield {"type": "token", "text": self.output}
                self._store.file_path(self._topic, "paper.pdf").write_bytes(b"%PDF-1.7 changed during summary")
                yield {
                    "type": "done",
                    "context": {"used": 500, "limit": context_limit, "estimated": False},
                    "model": model,
                }

        return events()


class _OversizedPrerequisiteModel(PrerequisiteFakeModel):
    def __init__(self):
        super().__init__(output="x" * (MAX_RESPONSE_BYTES + 100))


def test_default_ordinary_chat_success_ndjson_trace_and_persistence(tmp_path):
    model = FakeModel(token_text="baseline answer")
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            model_backend=model,
            structured_parser=_structured_parser,
        )
    )
    topic = client.post("/api/topics", json={"name": "Default chat"}).json()["id"]

    response = client.post(f"/api/topics/{topic}/chat", json=chat_payload(message="Question"))

    events = _parse_ndjson(response)
    assert response.status_code == 200
    assert _ndjson_types(response) == ["thinking", "token", "done"]
    assert len(model.calls) == 1
    messages = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert messages[-1]["content"] == "baseline answer"
    assert messages[-1].get("incomplete") is not True
    trace = _trace(client, topic)
    assert trace["status"] == "completed"
    assert trace["stage"] == "complete"
    assert trace["user_saved"] is True
    assert trace["assistant_saved"] is True


def test_named_conversation_ordinary_chat_success_ndjson_and_trace(tmp_path):
    model = FakeModel(token_text="named route answer")
    client = TestClient(create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=model))
    topic = client.post("/api/topics", json={"name": "Named"}).json()["id"]
    conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "Study"}).json()["id"]

    response = client.post(
        f"/api/topics/{topic}/conversations/{conversation}/chat",
        json=chat_payload(message="Named question"),
    )

    assert response.status_code == 200
    assert _ndjson_types(response) == ["thinking", "token", "done"]
    assert len(model.calls) == 1
    saved = client.get(f"/api/topics/{topic}/conversations/{conversation}/messages").json()["messages"]
    assert saved[-1]["content"] == "named route answer"
    trace = _trace(client, topic, conversation_id=conversation)
    assert trace["status"] == "completed"
    assert trace["conversation_id"] == conversation


def test_default_chat_provider_error_event_terminal_message_and_trace(tmp_path):
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            model_backend=_ProviderErrorEventModel(),
        )
    )
    topic = client.post("/api/topics", json={"name": "Provider error"}).json()["id"]

    response = client.post(f"/api/topics/{topic}/chat", json=chat_payload())

    events = _parse_ndjson(response)
    assert _ndjson_types(response) == ["thinking", "token", "error"]
    assert _terminal_message(events) == "synthetic mid-stream provider error"
    assistant = client.get(f"/api/topics/{topic}/messages").json()["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant.get("incomplete") is True
    assert assistant["content"] == "partial"
    trace = _trace(client, topic)
    assert trace["status"] == "error"
    assert trace["error"]["code"] == "provider_error"


def test_default_chat_premature_eof_terminal_message_and_trace(tmp_path):
    client = TestClient(
        create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=_PrematureEofModel())
    )
    topic = client.post("/api/topics", json={"name": "EOF"}).json()["id"]

    response = client.post(f"/api/topics/{topic}/chat", json=chat_payload())

    events = _parse_ndjson(response)
    assert _ndjson_types(response) == ["thinking", "token", "error"]
    assert _terminal_message(events) == (
        "Model stream ended before completion. Partial output was saved; retry when the local model service is ready."
    )
    trace = _trace(client, topic)
    assert trace["status"] == "error"
    assert trace["error"]["code"] == "premature_eof"


def test_default_chat_provider_exception_terminal_message_and_trace(tmp_path):
    client = TestClient(
        create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel(fail=True))
    )
    topic = client.post("/api/topics", json={"name": "Exception"}).json()["id"]

    response = client.post(f"/api/topics/{topic}/chat", json=chat_payload())

    events = _parse_ndjson(response)
    assert events[-1]["type"] == "error"
    assert _terminal_message(events) == (
        "Chat failed (RuntimeError). Check the local model service and retry; your message is saved."
    )
    trace = _trace(client, topic)
    assert trace["status"] == "error"
    assert trace["error"]["code"] == "generation_failed"


def test_extra_search_direct_answer_concatenated_token_text_and_metadata(tmp_path):
    answer_text = "The calibration value is exactly 42."
    model = EvidenceModel(
        [
            json.dumps(
                {
                    "action": "answer",
                    "answer": answer_text,
                    "source_labels": ["E1"],
                    "query": "",
                }
            )
        ]
    )
    app = evidence_app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "What value?",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    events = _parse_ndjson(response)
    assert response.status_code == 200
    assert _ndjson_types(response) == ["evidence_status", "evidence_status", "token", "done"]
    assert _concat_tokens(events) == answer_text
    assert len(model.calls) == 1
    done = events[-1]
    metadata = done["retrieval"]["evidence_search"]
    assert metadata["outcome"] == "direct_answer"
    assert metadata["generation_count"] == 1
    assert metadata["lookup_count"] == 0
    trace = _trace(client, topic)
    assert trace["status"] == "completed"
    assert trace["evidence_search"]["outcome"] == "direct_answer"


def test_extra_search_invalid_action_fallback_second_generation_zero_lookups(tmp_path):
    model = EvidenceModel(["not valid structured output"])
    app = evidence_app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Explain the value.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    events = _parse_ndjson(response)
    assert _ndjson_types(response) == ["evidence_status", "evidence_status", "token", "done"]
    assert len(model.calls) == 2
    done = events[-1]
    metadata = done["retrieval"]["evidence_search"]
    assert metadata["outcome"] == "invalid_action_fallback"
    assert metadata["generation_count"] == 2
    assert metadata["lookup_count"] == 0
    assert isinstance(metadata.get("warning"), str) and metadata["warning"]


def test_extra_search_lookup_path_two_generations_one_lookup(tmp_path):
    model = EvidenceModel(
        [
            json.dumps(
                {
                    "action": "search_selected",
                    "answer": "",
                    "source_labels": [],
                    "query": "validation value",
                }
            )
        ]
    )
    retrieval_calls: list[tuple[str, tuple[str, ...]]] = []
    app = evidence_app(tmp_path, model)
    app.state.deps.retriever = _search_retriever(retrieval_calls)
    client = TestClient(app)
    topic, record = _topic_with_index(client)
    second = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("second.pdf", b"%PDF-1.7\nsecond synthetic evidence", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    selected_ids = tuple(sorted((record["id"], second["id"])))

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "What value was validated?",
            "file_ids": list(selected_ids),
            "model": "local",
            "extra_search": True,
        },
    )

    events = _parse_ndjson(response)
    assert _ndjson_types(response) == [
        "evidence_status",
        "evidence_status",
        "evidence_status",
        "token",
        "done",
    ]
    assert len(model.calls) == 2
    metadata = events[-1]["retrieval"]["evidence_search"]
    assert metadata["outcome"] == "searched"
    assert metadata["generation_count"] == 2
    assert metadata["lookup_count"] == 1
    assert retrieval_calls == [
        ("What value was validated?", selected_ids),
        ("validation value", selected_ids),
    ]


def test_extra_search_incomplete_decision_single_generation_no_repair(tmp_path):
    model = _DecisionStreamModel("incomplete")
    app = evidence_app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Explain this source.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    events = _parse_ndjson(response)
    assert _ndjson_types(response) == ["evidence_status", "error"]
    assert _terminal_message(events) == _INVALID_OUTPUT
    assert len(model.calls) == 1
    saved = client.get(f"/api/topics/{topic}/messages").json()["messages"][-1]
    metadata = saved["retrieval"]["evidence_search"]
    assert saved.get("incomplete") is True
    assert metadata["outcome"] == "error"
    assert metadata["generation_count"] == 1
    trace = _trace(client, topic)
    assert trace["status"] == "error"
    assert trace["error"]["code"] == "incomplete_decision"


def test_extra_search_decision_provider_error_event_no_repair(tmp_path):
    model = _DecisionStreamModel("provider_error")
    app = evidence_app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    client = TestClient(app)
    topic, record = _topic_with_index(client)

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Explain this source.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    events = _parse_ndjson(response)
    assert _ndjson_types(response) == ["evidence_status", "error"]
    assert _terminal_message(events) == _PROVIDER_ERROR
    assert len(model.calls) == 1
    trace = _trace(client, topic)
    assert trace["status"] == "error"
    assert trace["error"]["code"] == "provider_failed"


def test_section_summary_success_exact_event_sequence_and_persistence(tmp_path):
    client, _store, topic, outline, model = summary_client_fixture(tmp_path)
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": False},
    )

    events = summary_events(response)
    assert response.status_code == 200
    assert [event["type"] for event in events] == ["started", "thinking", "token", "done"]
    assert len(model.summary_requests) == 1
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"]["status"] == "completed"
    assert saved["last_summary"]["content"] == "A synthetic statement [S1]."


def test_section_summary_provider_error_event_terminal_message(tmp_path):
    model = SummaryFakeModel(behavior="error")
    client, _, topic, outline, _ = summary_client_fixture(tmp_path, model=model)
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )

    events = summary_events(response)
    assert [event["type"] for event in events] == ["started", "thinking", "token", "error"]
    assert _terminal_message(events) == "synthetic provider failure"
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"]["status"] == "error"
    assert saved["last_summary"] is None


def test_section_summary_premature_eof_terminal_message(tmp_path):
    model = SummaryFakeModel(behavior="eof")
    client, _, topic, outline, _ = summary_client_fixture(tmp_path, model=model)
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )

    events = summary_events(response)
    assert [event["type"] for event in events] == ["started", "thinking", "token", "error"]
    assert _terminal_message(events) == "The model stream ended before completion."


def test_section_summary_unknown_source_label_validation_failure(tmp_path):
    model = SummaryFakeModel("Supported [S1], fabricated [S99].")
    client, _, topic, outline, _ = summary_client_fixture(tmp_path, model=model)
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )

    events = summary_events(response)
    assert events[-1]["type"] == "error"
    assert _terminal_message(events) == "The summary cited unknown source label [S99]; retry the summary."
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["last_summary"] is None


def test_section_summary_map_revision_changed_during_generation(tmp_path):
    client, store, topic, outline, _ = summary_client_fixture(tmp_path)
    model = _RevisionChangeSummaryModel(store, topic)
    client.app.state.deps.model_backend = model
    section = outline["sections"][0]
    response = client.post(
        _summary_url(topic, outline["revision"], section["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )

    events = summary_events(response)
    assert events[-1]["type"] == "error"
    assert _terminal_message(events) == "The source document changed while the summary was generating."
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"]["status"] == "interrupted"
    assert saved["last_summary"] is None


def test_section_summary_failed_regeneration_preserves_prior_success(tmp_path):
    model = SummaryFakeModel()
    client, _, topic, outline, _ = summary_client_fixture(tmp_path, model=model)
    section = outline["sections"][0]
    url = _summary_url(topic, outline["revision"], section["id"])
    body = {"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None}
    first_types = [event["type"] for event in summary_events(client.post(url, json=body))]
    assert first_types[-1] == "done"
    model.output = "Replacement without citations."
    failed_types = [event["type"] for event in summary_events(client.post(url, json=body))]
    assert failed_types == ["started", "thinking", "token", "error"]
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["last_summary"]["content"] == "A synthetic statement [S1]."


def test_prerequisites_success_pending_proficiency_and_event_sequence(tmp_path):
    client, topic, outline, model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]

    response = client.post(_generate_url(topic, section["id"]), json=_request(outline))

    events = prerequisite_events(response)
    assert response.status_code == 200
    assert [event["type"] for event in events] == ["started", "progress", "done"]
    assert len(model.requests) == 1
    done = events[-1]
    assert done["proficiency_revision"] == 1
    requirements = done["assessment"]["requirements"]
    assert len(requirements) == 2
    assert all(item["comfort_status"] == "pending" for item in requirements)
    profile = client.app.state.deps.profile_store.read_proficiency()
    assert len(profile["entries"]) == 2
    assert all(entry["comfort"] is None for entry in profile["entries"])


def test_prerequisites_provider_error_terminal_message_and_no_assessment(tmp_path):
    model = PrerequisiteFakeModel(behavior="error")
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]

    response = client.post(_generate_url(topic, section["id"]), json=_request(outline))

    events = prerequisite_events(response)
    assert [event["type"] for event in events] == ["started", "progress", "error"]
    assert _terminal_message(events) == "The local model could not complete prerequisite generation."
    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}").json()
    assert state["assessments"] == []
    assert state["attempts"][-1]["status"] == "error"
    assert client.app.state.deps.profile_store.read_proficiency()["entries"] == []


def test_prerequisites_oversized_stream_response(tmp_path):
    model = _OversizedPrerequisiteModel()
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]

    response = client.post(_generate_url(topic, section["id"]), json=_request(outline))

    events = prerequisite_events(response)
    assert events[-1]["type"] == "error"
    assert _terminal_message(events) == "The model response exceeded the allowed size; retry generation."
    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}").json()
    assert state["assessments"] == []


def test_prerequisites_invalid_json_never_exposes_partial_assessment(tmp_path):
    model = PrerequisiteFakeModel(output="not-json")
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]

    response = client.post(_generate_url(topic, section["id"]), json=_request(outline))

    events = prerequisite_events(response)
    assert [event["type"] for event in events] == ["started", "progress", "error"]
    assert _terminal_message(events) == "The model returned invalid prerequisite JSON; retry generation."
    state = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites?section_id={section['id']}").json()
    assert state["assessments"] == []
    assert state["current_assessment"] is None
    assert client.app.state.deps.profile_store.read_proficiency()["entries"] == []


def test_prerequisites_cv_changed_during_generation_no_pending_rows(tmp_path):
    model = PrerequisiteFakeModel()
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    profile_store = client.app.state.deps.profile_store
    next_cv = profile_store.register_cv(
        "Next CV.pdf", b"second original", "Changed synthetic background", {"status": "ready"}
    )

    def change_selection():
        profile = profile_store.read_profile()
        profile_store.select_cv(next_cv["id"], expected_revision=profile["revision"])

    model.on_done = change_selection
    section = outline["sections"][0]
    response = client.post(_generate_url(topic, section["id"]), json=_request(outline))

    events = prerequisite_events(response)
    assert events[-1]["type"] == "error"
    assert _terminal_message(events) == "The selected CV changed while prerequisites were generating; retry."
    assert profile_store.read_proficiency()["entries"] == []


def test_extra_search_preflight_refusal_leaves_no_saved_user_or_model_call(tmp_path):
    model = FakeModel()
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            model_backend=model,
            structured_parser=_structured_parser,
        )
    )
    topic = client.post("/api/topics", json={"name": "Preflight"}).json()["id"]

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Explain",
            "file_ids": [],
            "model": "local",
            "extra_search": True,
        },
    )

    assert response.status_code == 400
    assert client.get(f"/api/topics/{topic}/messages").json()["messages"] == []
    assert model.calls == []


def test_default_chat_trace_finalize_failure_after_answer_save(tmp_path, monkeypatch):
    import lab.web.chat as chat_module

    def fail_finalize(*_args, **_kwargs):
        raise OSError("private trace store detail")

    monkeypatch.setattr(chat_module, "finalize_trace", fail_finalize)
    model = FakeModel(token_text="saved answer")
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            model_backend=model,
        ),
        raise_server_exceptions=False,
    )
    topic = client.post("/api/topics", json={"name": "Trace finalize"}).json()["id"]

    response = client.post(f"/api/topics/{topic}/chat", json=chat_payload(message="Question"))

    events = _parse_ndjson(response)
    assert response.status_code == 200
    assert _ndjson_types(response) == ["thinking", "token", "error"]
    assert _terminal_message(events) == ("The answer was saved, but its query trace could not be finalized.")
    assert '"type": "done"' not in response.text
    assert client.get(f"/api/topics/{topic}/messages").json()["messages"][-1]["content"] == "saved answer"
    trace = _trace(client, topic)
    assert trace["status"] == "started"
    assert trace["assistant_saved"] is False


def test_extra_search_assistant_save_failure_terminal_sequence_and_trace(tmp_path):
    model = EvidenceModel(
        [json.dumps({"action": "answer", "answer": "Grounded.", "source_labels": ["E1"], "query": ""})]
    )
    app = evidence_app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    original_save = app.state.deps.store.save_session
    failed = False

    def fail_once(topic, session, conversation_id="default"):
        nonlocal failed
        if not failed and any(message["role"] == "assistant" for message in session["messages"]):
            failed = True
            raise OSError("private session file detail")
        return original_save(topic, session, conversation_id)

    app.state.deps.store.save_session = fail_once
    client = TestClient(app)
    topic, record = _topic_with_index(client)

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "Explain this source.",
            "file_ids": [record["id"]],
            "model": "local",
            "extra_search": True,
        },
    )

    events = _parse_ndjson(response)
    assert response.status_code == 200
    assert _ndjson_types(response) == ["evidence_status", "evidence_status", "token", "error"]
    assert _terminal_message(events) == (
        "Chat failed (OSError). Check the local model service and retry; your message is saved."
    )
    messages = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert [message["role"] for message in messages[-2:]] == ["user", "assistant"]
    assert messages[-1].get("incomplete") is True
    assert messages[-1]["retrieval"]["evidence_search"]["outcome"] == "error"
    trace = _trace(client, topic)
    assert trace["status"] == "error"
    assert trace["assistant_saved"] is True
    assert trace["error"]["code"] == "generation_failed"
