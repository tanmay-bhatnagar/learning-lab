"""Gate 11: summary admission LangGraph (real graph, fake production interfaces)."""

from __future__ import annotations

import inspect
import json
import pytest
from fastapi.testclient import TestClient

from lab.document_map_summary_store import write_summary_attempt
from lab.errors import Conflict, DoesNotFit
from lab.section_summary import build_section_summary_plan
from lab.workflows.summary import (
    SUMMARY_ADMISSION_NODE_NAMES,
    SUMMARY_ADMISSION_RECURSION_LIMIT,
    SummaryAdmissionContext,
    compile_summary_admission_graph,
    run_summary_admission,
)
from tests.test_document_map_summaries_api import SummaryFakeModel, _client, _summary_url
from tests.workflow_graph_introspection import draw_mermaid, graph_callables


def _admission_context(
    client: TestClient,
    topic: str,
    *,
    section_id: str,
    revision: str,
) -> SummaryAdmissionContext:
    deps = client.app.state.deps

    def list_active_attempt_ids() -> set[str]:
        return {
            attempt_id
            for attempt_id, active in deps.active_document_map_summaries.items()
            if active.topic == topic and active.file_id == "paper-1"
        }

    def register_active(attempt_id: str) -> None:
        from lab.web.deps import ActiveSummary

        deps.active_document_map_summaries[attempt_id] = ActiveSummary(
            topic=topic,
            file_id="paper-1",
            revision=revision,
            section_id=section_id,
        )

    return SummaryAdmissionContext(
        store=deps.store,
        runtime_policy_path=deps.config.runtime_policy_path,
        topic=topic,
        file_id="paper-1",
        section_id=section_id,
        expected_revision=revision,
        model="fake",
        context_limit=8192,
        think=None,
        register_active=register_active,
        list_active_attempt_ids=list_active_attempt_ids,
    )


@pytest.fixture
def admission_graph():
    return compile_summary_admission_graph()


def test_summary_admission_mermaid_contains_node_names(admission_graph) -> None:
    text = draw_mermaid(admission_graph)
    for name in SUMMARY_ADMISSION_NODE_NAMES:
        assert name in text


def test_summary_admission_graph_callables_are_coroutines(admission_graph) -> None:
    node_funcs = {
        name.removeprefix("node:"): fn for name, fn in graph_callables(admission_graph) if name.startswith("node:")
    }
    for name in SUMMARY_ADMISSION_NODE_NAMES:
        func = node_funcs[name]
        assert func is not None, name
        assert inspect.iscoroutinefunction(func), name
    assert SUMMARY_ADMISSION_RECURSION_LIMIT == len(SUMMARY_ADMISSION_NODE_NAMES) + 2


@pytest.mark.anyio
async def test_admission_stale_revision_raises_conflict_without_attempt(tmp_path, admission_graph) -> None:
    client, _, topic, outline, model = _client(tmp_path)
    section = outline["sections"][0]
    ctx = _admission_context(
        client,
        topic,
        section_id=section["id"],
        revision="0" * 64,
    )
    with pytest.raises(Conflict, match="revision changed"):
        await run_summary_admission(admission_graph, ctx)
    assert model.summary_requests == []
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"] is None


@pytest.mark.anyio
async def test_admission_oversized_policy_refuses_before_generating_attempt(tmp_path, admission_graph) -> None:
    client, _, topic, outline, model = _client(tmp_path, policy="synthetic policy " * 2000)
    section = outline["sections"][0]
    ctx = _admission_context(
        client,
        topic,
        section_id=section["id"],
        revision=outline["revision"],
    )
    ctx.context_limit = 1024
    with pytest.raises(DoesNotFit):
        await run_summary_admission(admission_graph, ctx)
    assert model.summary_requests == []
    saved = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert saved["latest_attempt"] is None


@pytest.mark.anyio
async def test_admission_plan_includes_policy_and_section_not_chat_context(
    tmp_path, admission_graph, monkeypatch
) -> None:
    import lab.workflows.summary as summary_module
    from lab.document_map_summary_store import write_summary_attempt

    client, _, topic, outline, _ = _client(tmp_path)
    section = outline["sections"][0]
    ctx = _admission_context(
        client,
        topic,
        section_id=section["id"],
        revision=outline["revision"],
    )
    writes: list[dict[str, object]] = []

    def capture_write(_store, _topic, _file_id, attempt, **_kwargs):
        writes.append(attempt)
        return write_summary_attempt(_store, _topic, _file_id, attempt, **_kwargs)

    monkeypatch.setattr(summary_module, "write_summary_attempt", capture_write)
    admitted = await run_summary_admission(admission_graph, ctx)
    messages = admitted.plan["messages"]
    payload = json.dumps(messages)
    assert "Synthetic full runtime policy." in messages[0]["content"]
    assert "Synthetic method source text." in messages[1]["content"]
    assert "PRIVATE HISTORY SENTINEL" not in payload
    assert "PRIVATE GOAL SENTINEL" not in payload
    assert writes and writes[0]["status"] == "generating"


@pytest.mark.anyio
async def test_admission_recovers_abandoned_generating_before_fit_refusal(tmp_path, admission_graph) -> None:
    client, store, topic, outline, model = _client(tmp_path)
    section = outline["sections"][0]
    plan = build_section_summary_plan(
        outline,
        section["id"],
        runtime_policy="Synthetic full runtime policy.",
        model="fake",
        context_limit=8192,
        think=None,
        attempt_id="abandoned-attempt",
        started_at="2026-10-05T00:00:00+00:00",
    )
    write_summary_attempt(store, topic, "paper-1", plan["attempt"])
    ctx = _admission_context(
        client,
        topic,
        section_id=section["id"],
        revision=outline["revision"],
    )
    ctx.context_limit = 1024
    ctx.runtime_policy_path = client.app.state.deps.config.runtime_policy_path
    policy_path = tmp_path / "huge-policy.md"
    policy_path.write_text("synthetic policy " * 2000, encoding="utf-8")
    ctx.runtime_policy_path = policy_path
    with pytest.raises(DoesNotFit):
        await run_summary_admission(admission_graph, ctx)
    assert model.summary_requests == []
    recovered = client.get(f"/api/topics/{topic}/files/paper-1/map").json()["map"]["sections"][0]
    assert recovered["latest_attempt"]["status"] == "interrupted"
    assert recovered["latest_attempt"]["id"] == "abandoned-attempt"


@pytest.mark.anyio
async def test_admission_does_not_call_model_stream_chat(tmp_path, admission_graph) -> None:
    model = SummaryFakeModel()
    client, _, topic, outline, _ = _client(tmp_path, model=model)
    section = outline["sections"][0]
    ctx = _admission_context(
        client,
        topic,
        section_id=section["id"],
        revision=outline["revision"],
    )
    await run_summary_admission(admission_graph, ctx)
    assert model.summary_requests == []


def test_http_admission_failure_releases_lease_and_skips_model(tmp_path) -> None:
    client, store, topic, outline, model = _client(tmp_path)
    store.file_path(topic, "paper.pdf").write_bytes(b"%PDF-1.7 changed after outline")
    response = client.post(
        _summary_url(topic, outline["revision"], outline["sections"][0]["id"]),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )
    assert response.status_code == 409
    assert model.summary_requests == []
    assert client.app.state.deps.active_document_map_summaries == {}
    assert not client.app.state.deps.locks[topic].locked()


def test_http_success_registers_active_summary_then_clears(tmp_path) -> None:
    client, _, topic, outline, _ = _client(tmp_path)
    section_id = outline["sections"][0]["id"]
    response = client.post(
        _summary_url(topic, outline["revision"], section_id),
        json={"revision": outline["revision"], "model": "fake", "context_limit": 8192, "think": None},
    )
    assert response.status_code == 200
    assert client.app.state.deps.active_document_map_summaries == {}
    assert not client.app.state.deps.locks[topic].locked()
