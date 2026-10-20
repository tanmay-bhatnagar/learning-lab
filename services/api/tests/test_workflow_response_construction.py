"""HTTP response-construction failures release already-owned workflow resources."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _setup_case(tmp_path, family: str):
    if family == "summary":
        import lab.web.document_map_summaries as routes
        from tests.test_document_map_summaries_api import _client
        from lab.web.schemas import SectionSummaryInput

        client, store, topic, outline, model = _client(tmp_path)
        section = outline["sections"][0]
        body = SectionSummaryInput(revision=outline["revision"], model="fake", context_limit=8192)
        args = (topic, "paper-1", section["id"], body)
        endpoint = routes.router(client.app.state.deps).routes[0].endpoint
    elif family == "prerequisite":
        import lab.web.prerequisites as routes
        from tests.test_web_prerequisites import _prepared

        client, topic, outline, model, _cv = _prepared(tmp_path)
        store = client.app.state.deps.store
        section = outline["sections"][0]
        body = routes.PrerequisiteInput(revision=outline["revision"], model="synthetic-model", context_limit=8192)
        args = (topic, "paper-1", section["id"], body)
        endpoint = routes.router(client.app.state.deps).routes[1].endpoint
    else:
        import lab.web.chat as routes
        from lab.web.schemas import ChatInput
        from tests.test_evidence_chat import EvidenceModel, _app, _retriever, _topic_with_index

        model = EvidenceModel()
        app = _app(tmp_path, model)
        app.state.deps.retriever = _retriever([])
        client = TestClient(app)
        topic, record = _topic_with_index(client)
        store = app.state.deps.store
        body = ChatInput(
            message="Synthetic question",
            model="local",
            context_limit=8192,
            file_ids=[record["id"]],
            extra_search=family == "optin",
        )
        args = (topic, body)
        endpoint = next(
            route.endpoint for route in routes.router(app.state.deps).routes if route.path == "/api/topics/{topic}/chat"
        )
    return routes, client, store, topic, model, endpoint, args


@pytest.mark.anyio
@pytest.mark.parametrize("family", ["ordinary", "optin", "summary", "prerequisite"])
async def test_response_constructor_failure_releases_owned_resources(tmp_path, monkeypatch, family):
    routes, client, store, topic, model, endpoint, args = _setup_case(tmp_path, family)

    def fail_response(*_args, **_kwargs):
        raise RuntimeError("synthetic response construction failure")

    monkeypatch.setattr(routes, "FinalizedStreamingResponse", fail_response)
    with pytest.raises(RuntimeError, match="response construction failure"):
        await endpoint(*args)

    deps = client.app.state.deps
    assert not deps.locks[topic].locked(), "admitted lease leaked after response construction failure"
    assert not deps.active_document_map_summaries
    assert not deps.active_prerequisite_attempts
    assert not deps.active_runs._runs

    if family in {"ordinary", "optin"}:
        assert model.calls == []
        messages = store.session(topic)["messages"]
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["incomplete"] is True
    elif family == "summary":
        assert model.summary_requests == []
        section = store.document_map(topic, "paper-1")["sections"][0]
        assert section["latest_attempt"]["status"] == "cancelled"
        assert section["last_summary"] is None
    else:
        from lab.prerequisite_store import get_prerequisite_state

        assert model.requests == []
        state = get_prerequisite_state(store, topic, "paper-1")
        assert state["attempts"][-1]["status"] == "cancelled"
        assert not state["assessments"]
