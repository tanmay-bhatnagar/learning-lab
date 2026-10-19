"""LangGraph prerequisite execution graph and publication tests."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator

import pytest

from lab.prerequisite_store import get_prerequisite_state, write_prerequisite_attempt
from lab.workflows.events import EventSink
from lab.workflows.prerequisites import (
    PREREQUISITE_EXECUTION_MERMAID,
    PrerequisiteAdmissionCapabilities,
    PrerequisiteExecutionBundle,
    admit_prerequisite_generation,
    build_prerequisite_graph_run,
    compile_prerequisite_admission_graph,
    compile_prerequisite_execution_graph,
    execution_callables_are_coroutines,
)
from lab.workflows.runtime import PublishOnce
from tests.test_web_prerequisites import (
    PrerequisiteFakeModel,
    _model_response,
    _prepared,
    _request,
    _seed_model_requirement,
    _write_generating_attempt,
)


def _patch_prerequisite_writes(monkeypatch, replacement) -> None:
    import lab.workflows.prerequisite_publication as prereq_publication
    import lab.workflows.prerequisites as prereq_workflow

    monkeypatch.setattr(prereq_workflow, "write_prerequisite_attempt", replacement)
    monkeypatch.setattr(prereq_publication, "write_prerequisite_attempt", replacement)


async def _execution_bundle(client, topic, outline, section, body, *, model: PrerequisiteFakeModel):
    deps = client.app.state.deps

    caps = PrerequisiteAdmissionCapabilities(
        store=deps.store,
        profile_store=deps.profile_store,
        runtime_policy_path=deps.config.runtime_policy_path,
        now=lambda: "2026-10-20T00:00:00+00:00",
        new_attempt_ids=lambda: (uuid.uuid4().hex, uuid.uuid4().hex),
        register_active=lambda _attempt_id: None,
    )
    admitted = await admit_prerequisite_generation(
        compile_prerequisite_admission_graph(),
        capabilities=caps,
        topic_id=topic,
        file_id="paper-1",
        section_id=section["id"],
        revision=body["revision"],
        model=body["model"],
        context_limit=body["context_limit"],
        think=body.get("think"),
        goal=body.get("goal"),
        active_attempt_ids=set(),
    )
    return PrerequisiteExecutionBundle(
        store=deps.store,
        profile_store=deps.profile_store,
        model_backend=model,
        generation_lock=deps.model_generation_lock,
        topic_id=topic,
        file_id="paper-1",
        section_id=section["id"],
        revision=body["revision"],
        model=body["model"],
        context_limit=body["context_limit"],
        think=body.get("think"),
        attempt_id=admitted.attempt_id,
        assessment_id=admitted.assessment_id,
        attempt=admitted.attempt,
        plan=admitted.plan,
        selected_cv=admitted.selected_cv,
        cv_text=admitted.cv_text,
        now=lambda: "2026-10-20T00:00:00+00:00",
    )


async def _run_execution(client, topic, outline, section, body, *, model: PrerequisiteFakeModel):
    bundle = await _execution_bundle(client, topic, outline, section, body, model=model)
    publish_once = PublishOnce()
    handle = build_prerequisite_graph_run(
        graph=compile_prerequisite_execution_graph(),
        bundle=bundle,
        publish_once=publish_once,
    )
    events: list[dict[str, object]] = []
    async for event in handle.run.events():
        events.append(dict(event))
    return events, handle, bundle


@pytest.mark.anyio
async def test_execution_mermaid_contains_node_names() -> None:
    for name in (
        "generate_buffered",
        "publish_stream_failure",
        "check_current_inputs",
        "validate_requirements",
        "register_pending",
        "publish_assessment",
    ):
        assert name in PREREQUISITE_EXECUTION_MERMAID


def test_execution_callables_are_async() -> None:
    assert execution_callables_are_coroutines()


@pytest.mark.anyio
async def test_success_registers_pending_then_publishes_assessment(tmp_path) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    body = _request(outline)
    events, handle, bundle = await _run_execution(client, topic, outline, section, body, model=model)

    assert [event["type"] for event in events] == ["progress", "done"]
    done = events[-1]
    assert done["attempt_id"] == bundle.attempt_id
    assert len(done["assessment"]["requirements"]) == 2  # type: ignore[index]
    profile = client.app.state.deps.profile_store.read_proficiency()
    assert len(profile["entries"]) == 2
    assert handle.context.artifacts.terminal is True


@pytest.mark.anyio
@pytest.mark.parametrize("behavior", ["error", "eof"], ids=["provider-error", "early-eof"])
async def test_provider_error_or_eof_terminal_without_assessment(tmp_path, behavior: str) -> None:
    model = PrerequisiteFakeModel(behavior=behavior)
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]
    events, _handle, bundle = await _run_execution(client, topic, outline, section, _request(outline), model=model)

    assert events[-1]["type"] == "error"
    if behavior == "error":
        assert events[-1]["message"] == "The local model could not complete prerequisite generation."
    else:
        assert events[-1]["message"] == "The model stream ended before completion."
    state = get_prerequisite_state(client.app.state.deps.store, topic, "paper-1")
    assert state["assessments"] == []
    assert state["attempts"][-1]["status"] == "error"
    assert client.app.state.deps.profile_store.read_proficiency()["entries"] == []
    assert bundle.attempt_id == events[-1]["attempt_id"]


class _OversizedPrerequisiteModel(PrerequisiteFakeModel):
    def stream_chat(self, *args, **kwargs) -> AsyncIterator[dict]:
        async def events() -> AsyncIterator[dict]:
            yield {"type": "token", "text": "x" * 30_000}
            yield {"type": "done", "model": "synthetic-model"}

        return events()


@pytest.mark.anyio
async def test_oversized_buffered_response_fails_before_publication(tmp_path) -> None:
    model = _OversizedPrerequisiteModel()
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]
    events, _, _ = await _run_execution(client, topic, outline, section, _request(outline), model=model)

    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == "The model response exceeded the allowed size; retry generation."


@pytest.mark.anyio
async def test_invalid_json_never_publishes_assessment(tmp_path) -> None:
    model = PrerequisiteFakeModel(output="not-json")
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    section = outline["sections"][0]
    events, _, _ = await _run_execution(client, topic, outline, section, _request(outline), model=model)

    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == "The model returned invalid prerequisite JSON; retry generation."
    assert get_prerequisite_state(client.app.state.deps.store, topic, "paper-1")["assessments"] == []


@pytest.mark.anyio
async def test_cv_changed_during_generation_prevents_registration(tmp_path) -> None:
    model = PrerequisiteFakeModel()
    client, topic, outline, model, _cv = _prepared(tmp_path, model=model)
    profile_store = client.app.state.deps.profile_store
    next_cv = profile_store.register_cv(
        "Next CV.pdf", b"second original", "Changed synthetic background", {"status": "ready"}
    )

    def change_selection() -> None:
        profile = profile_store.read_profile()
        profile_store.select_cv(next_cv["id"], expected_revision=profile["revision"])

    model.on_done = change_selection
    section = outline["sections"][0]
    events, _, _ = await _run_execution(client, topic, outline, section, _request(outline), model=model)

    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == "The selected CV changed while prerequisites were generating; retry."
    assert profile_store.read_proficiency()["entries"] == []


@pytest.mark.anyio
async def test_ambiguous_save_recognizes_published_assessment(tmp_path, monkeypatch) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    bundle = await _execution_bundle(client, topic, outline, section, _request(outline), model=model)

    def publish_then_raise(*args, assessment=None, **kwargs) -> None:
        write_prerequisite_attempt(*args, assessment=assessment, **kwargs)
        if assessment is not None:
            raise OSError("synthetic post-publish acknowledgement loss")

    _patch_prerequisite_writes(monkeypatch, publish_then_raise)
    publish_once = PublishOnce()
    handle = build_prerequisite_graph_run(
        graph=compile_prerequisite_execution_graph(),
        bundle=bundle,
        publish_once=publish_once,
    )
    events = [dict(event) async for event in handle.run.events()]

    assert events[-1]["type"] == "done"
    state = get_prerequisite_state(client.app.state.deps.store, topic, "paper-1")
    assert state["attempts"][-1]["status"] == "completed"


@pytest.mark.anyio
async def test_unreadable_state_keeps_rows_and_emits_uncertainty(tmp_path, monkeypatch) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    bundle = await _execution_bundle(client, topic, outline, section, _request(outline), model=model)
    deps = client.app.state.deps

    def corrupt_after_write(*args, assessment=None, **kwargs) -> None:
        if assessment is not None:
            path = deps.store.file_path(topic, "paper-1.prerequisites.json")
            path.write_text("{unreadable", encoding="utf-8")
            raise OSError("synthetic state readback failure")
        return write_prerequisite_attempt(*args, assessment=assessment, **kwargs)

    _patch_prerequisite_writes(monkeypatch, corrupt_after_write)
    publish_once = PublishOnce()
    handle = build_prerequisite_graph_run(
        graph=compile_prerequisite_execution_graph(),
        bundle=bundle,
        publish_once=publish_once,
    )
    events = [dict(event) async for event in handle.run.events()]

    assert events[-1]["type"] == "error"
    assert "attempt" not in events[-1]
    assert len(deps.profile_store.read_proficiency()["entries"]) == 2


@pytest.mark.anyio
async def test_failure_cleanup_preserves_manual_and_answered_rows(tmp_path, monkeypatch) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    deps = client.app.state.deps
    deps.profile_store.add_proficiency(
        concept="Manual Python",
        comfort="refresher",
        notes="Keep my own note",
        expected_revision=0,
    )
    response = json.loads(_model_response())
    response["requirements"].append(
        {
            "concept": "Statistics",
            "reason": "The section interprets likelihoods.",
            "source_labels": ["S1"],
            "cv_background": "not_stated",
            "cv_source_labels": [],
            "cv_quote": "",
        }
    )
    model.output = json.dumps(response)
    bundle = await _execution_bundle(client, topic, outline, section, _request(outline), model=model)

    def fail_publication(*args, assessment=None, **kwargs) -> None:
        if assessment is not None:
            profile = deps.profile_store.read_proficiency()
            generated = [entry for entry in profile["entries"] if entry.get("assessment_id") == bundle.assessment_id]
            deps.profile_store.save_proficiency_batch(
                additions=[],
                updates=[
                    {"id": generated[0]["id"], "comfort": "comfortable"},
                    {"id": generated[1]["id"], "notes": "Learner added this"},
                ],
                expected_revision=profile["revision"],
            )
            raise OSError("synthetic unpublished assessment write failure")
        return write_prerequisite_attempt(*args, assessment=assessment, **kwargs)

    _patch_prerequisite_writes(monkeypatch, fail_publication)
    publish_once = PublishOnce()
    handle = build_prerequisite_graph_run(
        graph=compile_prerequisite_execution_graph(),
        bundle=bundle,
        publish_once=publish_once,
    )
    events = [dict(event) async for event in handle.run.events()]

    assert events[-1]["type"] == "error"
    profile = deps.profile_store.read_proficiency()
    rows = [entry for entry in profile["entries"] if entry["source_kind"] == "model_requirement"]
    assert len(rows) == 2
    manual = [entry for entry in profile["entries"] if entry["source_kind"] == "user_manual"]
    assert len(manual) == 1


@pytest.mark.anyio
async def test_slow_consumer_blocks_producer_without_unbounded_queue() -> None:
    sink = EventSink(allowed_types=frozenset({"progress"}), capacity=8)
    assert sink._queue.maxsize == 8
    for _ in range(8):
        await sink.send({"type": "progress", "attempt_id": "a" * 32, "phase": "generating"})
    blocked = asyncio.create_task(sink.send({"type": "progress", "attempt_id": "a" * 32, "phase": "generating"}))
    await asyncio.sleep(0.05)
    assert not blocked.done()
    await sink.receive()
    await blocked


@pytest.mark.anyio
async def test_cancellation_during_publication_blocks_on_publish_once(tmp_path, monkeypatch) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    bundle = await _execution_bundle(client, topic, outline, section, _request(outline), model=model)
    entered = asyncio.Event()

    def blocking_write(*args, assessment=None, **kwargs) -> None:
        if assessment is not None:
            entered.set()
            time.sleep(2)
        return write_prerequisite_attempt(*args, assessment=assessment, **kwargs)

    _patch_prerequisite_writes(monkeypatch, blocking_write)
    publish_once = PublishOnce()
    handle = build_prerequisite_graph_run(
        graph=compile_prerequisite_execution_graph(),
        bundle=bundle,
        publish_once=publish_once,
    )
    consumer = asyncio.create_task(handle.run.result())
    await asyncio.wait_for(entered.wait(), timeout=2)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer


@pytest.mark.anyio
async def test_recovery_reconciles_orphan_pending_without_touching_published(tmp_path) -> None:
    client, topic, outline, _model, cv = _prepared(tmp_path)
    section = outline["sections"][0]
    deps = client.app.state.deps
    assessment_id = _write_generating_attempt(deps.store, topic, outline, section, cv)
    _seed_model_requirement(deps.profile_store, cv, topic, assessment_id)
    from lab.workflows.prerequisite_publication import recover_file_state

    recover_file_state(deps.store, deps.profile_store, topic, "paper-1", set(), now=lambda: "2026-10-20T00:00:00+00:00")
    assert get_prerequisite_state(deps.store, topic, "paper-1")["attempts"][-1]["status"] == "interrupted"
    assert deps.profile_store.read_proficiency()["entries"] == []


def _leaked_queue_get_tasks() -> list[asyncio.Task[object]]:
    return [
        item
        for item in asyncio.all_tasks()
        if item is not asyncio.current_task() and not item.done() and "Queue.get" in repr(item)
    ]


@pytest.mark.anyio
async def test_execution_consumer_leaves_no_queue_get_tasks(tmp_path) -> None:
    client, topic, outline, model, _cv = _prepared(tmp_path)
    section = outline["sections"][0]
    events, handle, _ = await _run_execution(client, topic, outline, section, _request(outline), model=model)
    assert events[-1]["type"] == "done"
    await handle.run.cancel_and_wait()
    assert _leaked_queue_get_tasks() == []
