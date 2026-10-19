"""Finite answer-or-search workflow contracts with injected local-model effects."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from lab.errors import Conflict
from lab.evidence_request import MAX_ACTION_BYTES, SourceImageReference, build_source_manifest


MODEL = "synthetic-local:latest"
FILE_IDS = ("selected-file",)


def _chunk(chunk_id: str, text: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "file_id": FILE_IDS[0],
        "file_name": "Selected.pdf",
        "chunk_index": 0,
        "text": text,
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "headings": [],
        "pages": [1],
        "bboxes": [],
        "asset_ids": [],
        "trace": {},
    }


def _plan(chunks: list[dict[str, object]], supplied_images=()) -> dict[str, object]:
    manifest = build_source_manifest(chunks)
    labels = {reference.source_id: reference.label for reference in manifest}
    citations = [
        {
            "chunk_id": chunk["chunk_id"],
            "file_id": chunk["file_id"],
            "file_name": chunk["file_name"],
            "headings": chunk["headings"],
            "pages": chunk["pages"],
            "bboxes": chunk["bboxes"],
            "assets": chunk["asset_ids"],
            "trace": chunk["trace"],
            "text": chunk["text"],
            "source_label": labels[chunk["chunk_id"]],
        }
        for chunk in chunks
    ]
    return {
        "prompt": [{"role": "user", "content": "Synthetic protected prompt."}],
        "prompt_context": {"used": 128, "estimated": False, "limit": 8192},
        "retained_indices": (),
        "citations": citations,
        "retrieval_record": {"mode": "keyword", "citations": citations},
        "source_manifest": manifest,
        "supplied_images": tuple(supplied_images),
    }


class ScriptedGateway:
    def __init__(self, generations):
        self.generations = list(generations)
        self.calls: list[dict[str, object]] = []

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
        call = {
            "messages": messages,
            "model": model,
            "think": think,
            "context_limit": context_limit,
            "context_metadata": context_metadata,
            "generation_lock": generation_lock,
            "response_schema": response_schema,
        }
        self.calls.append(call)
        script = self.generations.pop(0)

        async def stream():
            for event in script:
                yield event

        return stream()


def _token(text: str) -> dict[str, object]:
    return {"type": "token", "text": text}


def _thinking(text: str) -> dict[str, object]:
    return {"type": "thinking", "text": text}


def _done(used: int = 200, model: str = MODEL) -> dict[str, object]:
    return {"type": "done", "model": model, "context": {"used": used, "estimated": False}}


def _answer_action(text: str, labels: list[str] | None = None) -> str:
    return json.dumps({"action": "answer", "answer": text, "source_labels": labels or [], "query": ""})


async def _collect(workflow):
    return [event async for event in workflow]


def _workflow(
    gateway,
    *,
    initial_chunks,
    selected_file_ids=FILE_IDS,
    supplied_images=(),
    lookup=None,
    build_final=None,
    revalidate=None,
    initial_plan=None,
):
    from lab.evidence_turn import run_evidence_turn

    async def unavailable_lookup(query: str, *, file_ids: tuple[str, ...]):
        pytest.fail("The direct-answer path must not search")

    def identity_final(initial, additional):
        return _plan([*initial, *additional])

    def no_op_revalidate(sources, *, supplied_images):
        return None

    return run_evidence_turn(
        gateway=gateway,
        initial_plan=initial_plan or _plan(initial_chunks, supplied_images),
        initial_chunks=initial_chunks,
        selected_file_ids=selected_file_ids,
        model=MODEL,
        think=True,
        context_limit=8192,
        generation_lock=asyncio.Lock(),
        lookup=lookup or unavailable_lookup,
        build_final=build_final or identity_final,
        revalidate=revalidate or no_op_revalidate,
    )


def test_direct_validated_answer_uses_one_schema_call_and_emits_no_planning_json():
    source = _chunk("initial-1", "Initial retained source text.")
    action = _answer_action("The supported result is 12 units.", ["E1"])
    gateway = ScriptedGateway([[_thinking("private planner thought"), _token(action), _done()]])

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[source])))

    assert len(gateway.calls) == 1
    assert gateway.calls[0]["model"] == MODEL
    assert gateway.calls[0]["think"] is True
    assert gateway.calls[0]["response_schema"] is not None
    assert all(action not in str(event) for event in events)
    assert all("private planner thought" not in str(event) for event in events)
    assert events[0].kind == "stage" and events[0].stage == "deciding"
    assert [event.kind for event in events if event.kind == "token"] == ["token"]
    terminal = next(event for event in events if event.kind == "done")
    assert terminal.plan["citations"][0]["chunk_id"] == "initial-1"
    assert terminal.context == {"used": 200, "estimated": False}
    assert terminal.model == MODEL
    assert terminal.context["used"] != terminal.plan["prompt_context"]["used"]
    assert terminal.metadata["generation_count"] == 1
    assert terminal.metadata["lookup_count"] == 0


def test_search_closes_first_stream_scopes_lookup_and_supplies_validated_new_evidence():
    additional = _chunk("follow-up-1", "Selected document follow-up evidence.")
    action = json.dumps(
        {"action": "search_selected", "answer": "", "source_labels": [], "query": "Appendix comparison"}
    )
    closed = False
    looked_up: list[tuple[str, tuple[str, ...]]] = []

    class ClosingGateway(ScriptedGateway):
        def stream_chat(self, *args, **kwargs):
            call = super().stream_chat(*args, **kwargs)
            if len(self.calls) != 1:
                return call

            async def first_stream():
                nonlocal closed
                try:
                    async for event in call:
                        yield event
                    await asyncio.Event().wait()
                finally:
                    closed = True

            return first_stream()

    async def lookup(query: str, *, file_ids: tuple[str, ...]):
        assert closed
        looked_up.append((query, file_ids))
        return {
            "hits": [additional],
            "mode": "fallback",
            "warning": "private search query: Appendix comparison; CV_SECRET_731.",
        }

    gateway = ClosingGateway(
        [
            [_thinking("private planner thought"), _token(action), _done(used=777)],
            [_thinking("final answer reasoning"), _token("Final supported answer."), _done(used=333)],
        ]
    )
    initial = _chunk("initial-1", "Initial retained evidence.")
    revalidated: list[tuple[str, ...]] = []

    def revalidate(sources, *, supplied_images):
        revalidated.append(tuple(source["chunk_id"] for source in sources))

    events = asyncio.run(
        _collect(
            _workflow(
                gateway,
                initial_chunks=[initial],
                lookup=lookup,
                revalidate=revalidate,
            )
        )
    )

    assert len(gateway.calls) == 2
    assert all(call["model"] == MODEL for call in gateway.calls)
    assert gateway.calls[0]["response_schema"] is not None
    assert gateway.calls[1]["response_schema"] is None
    assert gateway.calls[0]["think"] is True
    assert gateway.calls[1]["think"] is True
    assert all("private planner thought" not in str(event) for event in events)
    assert any(event.kind == "thinking" and event.text == "final answer reasoning" for event in events)
    assert looked_up == [("Appendix comparison", FILE_IDS)]
    assert revalidated
    assert revalidated[-1] == ("initial-1", "follow-up-1")
    terminal = next(event for event in events if event.kind == "done")
    assert terminal.context == {"used": 333, "estimated": False}
    assert terminal.model == MODEL
    assert {citation["chunk_id"] for citation in terminal.plan["citations"]} == {"initial-1", "follow-up-1"}
    assert terminal.metadata["generation_count"] == 2
    assert terminal.metadata["lookup_count"] == 1
    assert terminal.metadata["search_mode"] == "fallback"
    assert terminal.metadata["search_warning"] == (
        "Selected-document search used bounded opening passages because no query match was found."
    )
    assert "Appendix comparison" not in json.dumps(terminal.metadata)
    assert all("private search query" not in str(event) and "CV_SECRET_731" not in str(event) for event in events)


def test_revalidation_receives_accumulated_initial_images_even_when_final_plan_trims_them():
    initial = _chunk("initial-image", "Source passage with an attached figure.")
    initial["asset_ids"] = ["plot.png"]
    additional = _chunk("follow-up", "New text passage.")
    image = SourceImageReference(
        source_id="initial-image",
        file_id=FILE_IDS[0],
        asset_name="plot.png",
        content_sha256="a" * 64,
    )
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "more detail"})
    gateway = ScriptedGateway([[_token(action), _done()], [_token("Final."), _done()]])
    revalidated: list[tuple[tuple[str, ...], tuple[SourceImageReference, ...]]] = []

    async def lookup(query: str, *, file_ids: tuple[str, ...]):
        return {"hits": [additional], "mode": "keyword"}

    def build_final(initial_hits, additional_hits):
        return _plan(list(additional_hits))

    def revalidate(sources, *, supplied_images):
        revalidated.append((tuple(source["chunk_id"] for source in sources), tuple(supplied_images)))

    events = asyncio.run(
        _collect(
            _workflow(
                gateway,
                initial_chunks=[initial],
                supplied_images=[image],
                lookup=lookup,
                build_final=build_final,
                revalidate=revalidate,
            )
        )
    )

    expected_image = (image,)
    assert revalidated[0] == (("initial-image",), expected_image)
    assert revalidated[1] == (("initial-image",), expected_image)
    assert revalidated[-1] == (("initial-image", "follow-up"), expected_image)
    terminal = next(event for event in events if event.kind == "done")
    assert terminal.plan["citations"][0]["chunk_id"] == "follow-up"
    assert terminal.plan["supplied_images"] == ()


def test_empty_captured_indexed_scope_fails_before_provider_call():
    gateway = ScriptedGateway([[_token("unused"), _done()]])

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[], selected_file_ids=())))

    assert gateway.calls == []
    assert any(event.kind == "error" for event in events)


def test_search_is_allowed_with_empty_initial_manifest_and_explicit_indexed_scope():
    additional = _chunk("follow-up-only", "Selected indexed passage.")
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "specific detail"})
    gateway = ScriptedGateway([[_token(action), _done()], [_token("Answer."), _done()]])
    looked_up: list[tuple[str, tuple[str, ...]]] = []

    async def lookup(query: str, *, file_ids: tuple[str, ...]):
        looked_up.append((query, file_ids))
        return {"hits": [additional], "mode": "keyword"}

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[], lookup=lookup)))

    assert len(gateway.calls) == 2
    assert looked_up == [("specific detail", FILE_IDS)]
    terminal = next(event for event in events if event.kind == "done")
    assert [citation["chunk_id"] for citation in terminal.plan["citations"]] == ["follow-up-only"]


@pytest.mark.parametrize(
    ("first_stream", "expected_calls"),
    [
        ([_token("not valid JSON"), _done()], 2),
        (
            [
                _token(
                    json.dumps(
                        {
                            "action": "answer",
                            "answer": "partial",
                            "source_labels": [],
                            "query": "private search text",
                        }
                    )
                ),
                _done(),
            ],
            2,
        ),
        ([_token(_answer_action("partial"))], 1),
        ([{"type": "error", "message": "provider unavailable"}], 1),
    ],
)
def test_first_stream_falls_back_only_after_completed_invalid_action(first_stream, expected_calls):
    gateway = ScriptedGateway([first_stream, [_token("fallback answer"), _done()]])
    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[])))

    assert len(gateway.calls) == expected_calls
    if expected_calls == 1:
        assert any(event.kind == "error" for event in events)
    else:
        terminal = next(event for event in events if event.kind == "done")
        assert terminal.metadata["generation_count"] == 2
        assert terminal.metadata.get("warning")
        assert "private search text" not in str(terminal.metadata)


def test_action_stream_buffer_is_bounded_before_joining_and_never_falls_back():
    oversized = "x" * (MAX_ACTION_BYTES + 1)
    gateway = ScriptedGateway([[_token(oversized), _done()], [_token("must not run"), _done()]])

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[])))

    assert len(gateway.calls) == 1
    assert any(event.kind == "error" for event in events)


def test_action_buffer_counts_utf8_bytes_across_multiple_unicode_fragments():
    fragment = "🧠" * (MAX_ACTION_BYTES // 4)
    gateway = ScriptedGateway([[_token(fragment), _token(fragment), _done()]])

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[])))

    assert len(gateway.calls) == 1
    error = next(event for event in events if event.kind == "error")
    assert error.error_code == "action_too_large"


def test_invalid_action_fallback_reports_actual_final_retained_ids():
    initial = [_chunk("initial-1", "First passage."), _chunk("initial-2", "Second passage.")]
    gateway = ScriptedGateway([[_token("not JSON"), _done()], [_token("Fallback answer."), _done()]])
    final_plan = _plan([initial[0]])

    events = asyncio.run(
        _collect(_workflow(gateway, initial_chunks=initial, build_final=lambda _initial, _extra: final_plan))
    )

    terminal = next(event for event in events if event.kind == "done")
    assert terminal.metadata["final_chunk_ids"] == ["initial-1"]
    assert [citation["chunk_id"] for citation in terminal.plan["citations"]] == ["initial-1"]


def test_search_refuses_a_returned_hit_outside_captured_scope():
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
    gateway = ScriptedGateway([[_token(action), _done()]])

    async def lookup(_query: str, *, file_ids: tuple[str, ...]):
        outside = _chunk("outside", "Not selected.")
        outside["file_id"] = "other-file"
        return {"hits": [outside], "mode": "keyword"}

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[], lookup=lookup)))

    assert len(gateway.calls) == 1
    error = next(event for event in events if event.kind == "error")
    assert error.error_code == "invalid_lookup_result"


def test_changed_snapshot_before_lookup_stops_without_search_or_final_generation():
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
    gateway = ScriptedGateway([[_token(action), _done()]])
    lookups: list[str] = []
    guards = 0

    async def lookup(query: str, *, file_ids: tuple[str, ...]):
        lookups.append(query)
        return {"hits": [], "mode": "none"}

    def revalidate(_sources, *, supplied_images):
        nonlocal guards
        guards += 1
        if guards == 2:
            from lab.errors import InvalidInput

            raise InvalidInput("snapshot changed")

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[], lookup=lookup, revalidate=revalidate)))

    assert guards == 2
    assert lookups == []
    assert len(gateway.calls) == 1
    assert next(event for event in events if event.kind == "error").error_code == "snapshot_changed"


def test_search_rejects_changed_text_for_an_existing_source_id_before_final_build():
    initial = _chunk("same-id", "Original source text.")
    changed = _chunk("same-id", "Changed source text.")
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
    gateway = ScriptedGateway([[_token(action), _done()]])
    built: list[bool] = []

    async def lookup(_query: str, *, file_ids: tuple[str, ...]):
        return {"hits": [changed], "mode": "hybrid"}

    def build_final(initial_hits, additional_hits):
        built.append(True)
        return _plan([*initial_hits, *additional_hits])

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[initial], lookup=lookup, build_final=build_final)))

    assert built == []
    assert len(gateway.calls) == 1
    assert next(event for event in events if event.kind == "error").error_code == "invalid_lookup_result"


def test_search_reports_new_but_trimmed_ids_separately_from_retained_ids():
    initial_available = [_chunk("initial-1", "Initial passage."), _chunk("initial-2", "Available but trimmed.")]
    initial_plan = _plan([initial_available[0]])
    additional = _chunk("new-1", "New passage.")
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
    gateway = ScriptedGateway([[_token(action), _done()], [_token("Answer."), _done()]])

    async def lookup(_query: str, *, file_ids: tuple[str, ...]):
        return {"hits": [initial_available[1], additional], "mode": "hybrid"}

    def build_final(_initial, _additional):
        return _plan([initial_available[0]])

    events = asyncio.run(
        _collect(
            _workflow(
                gateway,
                initial_chunks=initial_available,
                initial_plan=initial_plan,
                lookup=lookup,
                build_final=build_final,
            )
        )
    )

    terminal = next(event for event in events if event.kind == "done")
    assert terminal.metadata["initial_chunk_ids"] == ["initial-1"]
    assert terminal.metadata["new_chunk_ids"] == ["new-1"]
    assert terminal.metadata["retained_new_chunk_ids"] == []
    assert terminal.metadata["final_chunk_ids"] == ["initial-1"]


def test_final_provider_empty_answer_is_not_reported_as_success():
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
    gateway = ScriptedGateway([[_token(action), _done()], [_done()]])

    async def lookup(_query: str, *, file_ids: tuple[str, ...]):
        return {"hits": [], "mode": "none"}

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[], lookup=lookup)))

    assert not any(event.kind == "done" for event in events)
    assert next(event for event in events if event.kind == "error").error_code == "incomplete_answer"


@pytest.mark.parametrize("final_stream", [[_token("partial")], [{"type": "error", "message": "private"}]])
def test_final_provider_failure_or_missing_done_is_incomplete(final_stream):
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
    gateway = ScriptedGateway([[_token(action), _done()], final_stream])

    async def lookup(_query: str, *, file_ids: tuple[str, ...]):
        return {"hits": [], "mode": "none"}

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[], lookup=lookup)))

    assert not any(event.kind == "done" for event in events)
    assert next(event for event in events if event.kind == "error").text == (
        "Evidence generation could not complete. Try again."
    )


def test_direct_answer_declares_only_its_noncontiguous_retained_sources():
    chunks = [_chunk(f"source-{i}", f"Passage {i}.") for i in range(1, 4)]
    action = _answer_action("Supported by E1 and E3.", ["E1", "E3"])
    gateway = ScriptedGateway([[_token(action), _done()]])

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=chunks)))

    terminal = next(event for event in events if event.kind == "done")
    assert terminal.metadata["declared_source_labels"] == ["E1", "E3"]
    assert terminal.metadata["initial_chunk_ids"] == ["source-1", "source-2", "source-3"]
    assert terminal.metadata["final_chunk_ids"] == ["source-1", "source-2", "source-3"]


def test_direct_answer_can_declare_no_sources_while_initial_citations_remain_available():
    chunks = [_chunk("source-1", "Available passage."), _chunk("source-2", "Another passage.")]
    gateway = ScriptedGateway([[_token(_answer_action("A general response.")), _done()]])

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=chunks)))

    terminal = next(event for event in events if event.kind == "done")
    assert terminal.metadata["declared_source_labels"] == []
    assert terminal.metadata["final_chunk_ids"] == ["source-1", "source-2"]
    assert {citation["chunk_id"] for citation in terminal.plan["citations"]} == {"source-1", "source-2"}


def test_duplicate_only_lookup_does_not_claim_new_or_retained_new_evidence():
    initial = _chunk("initial-1", "Initial passage.")
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
    gateway = ScriptedGateway([[_token(action), _done()], [_token("Answer."), _done()]])

    async def lookup(_query: str, *, file_ids: tuple[str, ...]):
        return {"hits": [initial], "mode": "hybrid"}

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[initial], lookup=lookup)))

    terminal = next(event for event in events if event.kind == "done")
    assert terminal.metadata["returned_chunk_ids"] == ["initial-1"]
    assert terminal.metadata["new_chunk_ids"] == []
    assert terminal.metadata["retained_new_chunk_ids"] == []


def test_cancellation_closes_model_stream_and_releases_shared_lock():
    async def scenario():
        entered = asyncio.Event()
        lock = asyncio.Lock()
        closed = False

        class BlockingGateway:
            def stream_chat(self, *_args, **_kwargs):
                async def stream():
                    nonlocal closed
                    await lock.acquire()
                    try:
                        yield _token("{")
                        entered.set()
                        await asyncio.Event().wait()
                    finally:
                        closed = True
                        lock.release()

                return stream()

        workflow = _workflow(BlockingGateway(), initial_chunks=[])
        task = asyncio.create_task(_collect(workflow))
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed
        assert not lock.locked()

    asyncio.run(scenario())


def test_cancellation_during_lookup_cancels_lookup_and_does_not_start_final_call():
    async def scenario():
        lookup_started = asyncio.Event()
        lookup_closed = False
        action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
        gateway = ScriptedGateway([[_token(action), _done()]])

        async def lookup(_query: str, *, file_ids: tuple[str, ...]):
            nonlocal lookup_closed
            lookup_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                lookup_closed = True

        task = asyncio.create_task(_collect(_workflow(gateway, initial_chunks=[], lookup=lookup)))
        await asyncio.wait_for(lookup_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert lookup_closed
        assert len(gateway.calls) == 1

    asyncio.run(scenario())


def test_cancellation_during_final_stream_closes_it_and_releases_lock():
    async def scenario():
        final_started = asyncio.Event()
        lock = asyncio.Lock()
        final_closed = False
        action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})

        class Gateway:
            calls = 0

            def stream_chat(self, *_args, **_kwargs):
                self.calls += 1
                call = self.calls

                async def stream():
                    nonlocal final_closed
                    await lock.acquire()
                    try:
                        if call == 1:
                            yield _token(action)
                            yield _done()
                            return
                        yield _token("Partial answer")
                        final_started.set()
                        await asyncio.Event().wait()
                    finally:
                        if call == 2:
                            final_closed = True
                        lock.release()

                return stream()

        async def lookup(_query: str, *, file_ids: tuple[str, ...]):
            return {"hits": [], "mode": "none"}

        gateway = Gateway()
        task = asyncio.create_task(_collect(_workflow(gateway, initial_chunks=[], lookup=lookup)))
        await asyncio.wait_for(final_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert final_closed
        assert not lock.locked()

    asyncio.run(scenario())


def test_stopping_at_deciding_stage_closes_the_created_gateway_iterator():
    class OwnedStream:
        closed = False

        def __aiter__(self):
            async def events():
                yield _token("unused")
                yield _done()

            return events()

        async def aclose(self):
            self.closed = True

    class Gateway:
        stream = OwnedStream()

        def stream_chat(self, *_args, **_kwargs):
            return self.stream

    async def scenario():
        gateway = Gateway()
        workflow = _workflow(gateway, initial_chunks=[])
        assert (await anext(workflow)).stage == "deciding"
        assert (await anext(workflow)).stage == "deciding"
        await workflow.aclose()
        assert gateway.stream.closed

    asyncio.run(scenario())


def test_initial_sources_are_not_reported_supplied_before_gateway_factory_returns():
    initial = _chunk("initial-1", "Prepared initial passage.")
    gateway = ScriptedGateway([[_token(_answer_action("Supported answer.")), _done()]])

    async def scenario():
        workflow = _workflow(gateway, initial_chunks=[initial])
        prepared = await anext(workflow)
        assert prepared.stage == "deciding"
        assert prepared.metadata["initial_available_chunk_ids"] == ["initial-1"]
        assert prepared.metadata["initial_chunk_ids"] == []
        assert prepared.metadata["final_chunk_ids"] == []
        dispatched = await anext(workflow)
        assert dispatched.stage == "deciding"
        assert dispatched.metadata["generation_count"] == 1
        assert dispatched.metadata["initial_chunk_ids"] == ["initial-1"]
        assert dispatched.metadata["final_chunk_ids"] == ["initial-1"]
        await workflow.aclose()

    asyncio.run(scenario())
    assert len(gateway.calls) == 1


def test_initial_snapshot_conflict_does_not_claim_prepared_sources_were_supplied():
    initial = _chunk("initial-1", "Prepared initial passage.")
    gateway = ScriptedGateway([[_token("unused"), _done()]])
    revalidated: list[tuple[str, ...]] = []

    def revalidate(sources, *, supplied_images):
        revalidated.append(tuple(source["chunk_id"] for source in sources))
        raise Conflict("snapshot changed")

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[initial], revalidate=revalidate)))

    error = next(event for event in events if event.kind == "error")
    assert revalidated == [("initial-1",)]
    assert gateway.calls == []
    assert error.metadata["generation_count"] == 0
    assert error.metadata["initial_available_chunk_ids"] == ["initial-1"]
    assert error.metadata["initial_chunk_ids"] == []
    assert error.metadata["final_chunk_ids"] == []


def test_initial_gateway_factory_failure_counts_attempt_without_claiming_sources():
    initial = _chunk("initial-1", "Prepared initial passage.")

    class Gateway:
        calls = 0

        def stream_chat(self, *_args, **_kwargs):
            self.calls += 1
            raise RuntimeError("private gateway failure")

    gateway = Gateway()
    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[initial])))

    error = next(event for event in events if event.kind == "error")
    assert gateway.calls == 1
    assert error.metadata["generation_count"] == 1
    assert error.metadata["initial_available_chunk_ids"] == ["initial-1"]
    assert error.metadata["initial_chunk_ids"] == []
    assert error.metadata["final_chunk_ids"] == []


def test_final_plan_event_follows_gateway_dispatch_and_counts_the_attempt():
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
    gateway = ScriptedGateway([[_token(action), _done()], [_token("unused"), _done()]])

    async def lookup(_query: str, *, file_ids: tuple[str, ...]):
        return {"hits": [], "mode": "none"}

    async def scenario():
        workflow = _workflow(gateway, initial_chunks=[], lookup=lookup)
        async for event in workflow:
            if event.kind == "plan":
                assert event.metadata["generation_count"] == 2
                assert len(gateway.calls) == 2
                await workflow.aclose()
                return
        pytest.fail("Expected a final plan event")

    asyncio.run(scenario())


def test_search_attempt_is_started_before_search_stage_and_cancelled_when_stopped():
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})
    gateway = ScriptedGateway([[_token(action), _done()]])
    invoked: list[str] = []
    cleaned = False
    started = asyncio.Event()

    def lookup(query: str, *, file_ids: tuple[str, ...]):
        invoked.append(query)

        async def waiting():
            nonlocal cleaned
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned = True

        return waiting()

    async def scenario():
        workflow = _workflow(gateway, initial_chunks=[], lookup=lookup)
        async for event in workflow:
            if event.stage == "searching":
                await asyncio.wait_for(started.wait(), timeout=1)
                assert invoked == ["details"]
                assert event.metadata["lookup_count"] == 1
                await workflow.aclose()
                return
        pytest.fail("Expected a searching stage")

    asyncio.run(scenario())
    assert cleaned


def test_final_gateway_factory_failure_does_not_claim_prepared_sources_were_supplied():
    initial = _chunk("initial-1", "Initial passage.")
    additional = _chunk("new-1", "Prepared follow-up passage.")
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})

    class Gateway:
        calls = 0

        def stream_chat(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("private gateway failure")

            async def first():
                yield _token(action)
                yield _done()

            return first()

    async def lookup(_query: str, *, file_ids: tuple[str, ...]):
        return {"hits": [additional], "mode": "hybrid"}

    events = asyncio.run(_collect(_workflow(Gateway(), initial_chunks=[initial], lookup=lookup)))

    error = next(event for event in events if event.kind == "error")
    assert error.metadata["generation_count"] == 2
    assert error.metadata["initial_chunk_ids"] == ["initial-1"]
    assert error.metadata["final_chunk_ids"] == ["initial-1"]
    assert error.metadata["retained_new_chunk_ids"] == []


def test_stopping_at_final_plan_closes_the_dispatched_gateway_iterator():
    action = json.dumps({"action": "search_selected", "answer": "", "source_labels": [], "query": "details"})

    class OwnedStream:
        closed = False

        def __aiter__(self):
            async def events():
                yield _token("unused")
                yield _done()

            return events()

        async def aclose(self):
            self.closed = True

    class Gateway:
        calls = 0
        final_stream = OwnedStream()

        def stream_chat(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:

                async def first():
                    yield _token(action)
                    yield _done()

                return first()
            return self.final_stream

    async def lookup(_query: str, *, file_ids: tuple[str, ...]):
        return {"hits": [], "mode": "none"}

    async def scenario():
        gateway = Gateway()
        workflow = _workflow(gateway, initial_chunks=[], lookup=lookup)
        async for event in workflow:
            if event.kind == "plan":
                await workflow.aclose()
                break
        assert gateway.final_stream.closed

    asyncio.run(scenario())


def test_snapshot_conflict_is_a_safe_error_and_stops_all_following_effects():
    from lab.errors import Conflict

    gateway = ScriptedGateway([[_token(_answer_action("unused")), _done()]])

    def revalidate(_sources, *, supplied_images):
        raise Conflict("private snapshot identity")

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[], revalidate=revalidate)))

    assert gateway.calls == []
    error = next(event for event in events if event.kind == "error")
    assert error.error_code == "snapshot_changed"
    assert "private snapshot identity" not in str(error)
