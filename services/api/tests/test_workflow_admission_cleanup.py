"""Ownership after final admission writes and failed execution cleanup."""

from __future__ import annotations

import asyncio

import pytest

from tests.test_workflow_response_construction import _setup_case


@pytest.mark.anyio
@pytest.mark.parametrize("family", ["summary", "prerequisite"])
async def test_cancel_after_admission_write_releases_active_attempt(tmp_path, monkeypatch, family):
    if family == "summary":
        import lab.workflows.summary as workflow
    else:
        import lab.workflows.prerequisites as workflow

    routes, client, _store, topic, model, endpoint, args = _setup_case(tmp_path, family)
    original_write = workflow.write_generating_attempt
    request_task = None

    async def cancel_after_write(state, runtime):
        result = await original_write(state, runtime)
        request_task.cancel()
        return result

    monkeypatch.setattr(workflow, "write_generating_attempt", cancel_after_write)
    endpoint = next(route.endpoint for route in routes.router(client.app.state.deps).routes if "POST" in route.methods)
    request_task = asyncio.create_task(endpoint(*args))
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(request_task, timeout=1)

    deps = client.app.state.deps
    assert not deps.locks[topic].locked()
    assert not deps.active_document_map_summaries
    assert not deps.active_prerequisite_attempts
    if family == "summary":
        assert model.summary_requests == []
        response = client.get(f"/api/topics/{topic}/files/paper-1/map")
        assert response.status_code == 200
        assert response.json()["map"]["sections"][0]["latest_attempt"]["status"] == "interrupted"
    else:
        assert model.requests == []
        response = client.get(f"/api/topics/{topic}/files/paper-1/prerequisites")
        assert response.status_code == 200
        assert response.json()["attempts"][-1]["status"] == "interrupted"


@pytest.mark.anyio
async def test_prerequisite_cleanup_failure_deregisters_attempt(tmp_path, monkeypatch):
    from lab.workflows.runtime import GraphRun

    routes, client, _store, topic, _model, endpoint, args = _setup_case(tmp_path, "prerequisite")

    async def fail_cleanup(_self):
        raise OSError("synthetic cleanup failure")

    def fail_response(*_args, **_kwargs):
        raise RuntimeError("original response failure")

    monkeypatch.setattr(GraphRun, "cancel_and_wait", fail_cleanup)
    monkeypatch.setattr(routes, "FinalizedStreamingResponse", fail_response)
    with pytest.raises(RuntimeError, match="original response failure"):
        await endpoint(*args)
    assert not client.app.state.deps.locks[topic].locked()
    assert not client.app.state.deps.active_prerequisite_attempts
