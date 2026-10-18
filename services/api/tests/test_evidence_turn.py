"""Finite answer-or-search workflow contracts with injected local-model effects."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from lab.evidence_request import MAX_ACTION_BYTES, build_source_manifest


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


def _plan(chunks: list[dict[str, object]]) -> dict[str, object]:
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


def _done() -> dict[str, object]:
    return {"type": "done", "model": MODEL, "context": {"used": 200, "estimated": False}}


def _answer_action(text: str, labels: list[str] | None = None) -> str:
    return json.dumps({"action": "answer", "answer": text, "source_labels": labels or [], "query": ""})


async def _collect(workflow):
    return [event async for event in workflow]


def _workflow(gateway, *, initial_chunks, selected_file_ids=FILE_IDS, lookup=None, build_final=None, revalidate=None):
    from lab.evidence_turn import run_evidence_turn

    async def unavailable_lookup(query: str, *, file_ids: tuple[str, ...]):
        pytest.fail("The direct-answer path must not search")

    def identity_final(initial, additional):
        return _plan([*initial, *additional])

    def no_op_revalidate(sources):
        return None

    return run_evidence_turn(
        gateway=gateway,
        initial_plan=_plan(initial_chunks),
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
            "warning": "No query match; using opening passages from the selected file.",
        }

    gateway = ClosingGateway(
        [
            [_thinking("private planner thought"), _token(action), _done()],
            [_thinking("final answer reasoning"), _token("Final supported answer."), _done()],
        ]
    )
    revalidated: list[tuple[str, ...]] = []

    def revalidate(sources):
        revalidated.append(tuple(source["chunk_id"] for source in sources))

    events = asyncio.run(
        _collect(
            _workflow(
                gateway,
                initial_chunks=[],
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
    assert revalidated[-1] == ("follow-up-1",)
    terminal = next(event for event in events if event.kind == "done")
    assert {citation["chunk_id"] for citation in terminal.plan["citations"]} == {"follow-up-1"}
    assert terminal.metadata["generation_count"] == 2
    assert terminal.metadata["lookup_count"] == 1
    assert terminal.metadata["search_mode"] == "fallback"
    assert terminal.metadata["search_warning"] == "No query match; using opening passages from the selected file."
    assert "Appendix comparison" not in json.dumps(terminal.metadata)


def test_empty_captured_indexed_scope_fails_before_provider_call():
    gateway = ScriptedGateway([[_token("unused"), _done()]])

    events = asyncio.run(_collect(_workflow(gateway, initial_chunks=[], selected_file_ids=())))

    assert gateway.calls == []
    assert any(event.kind == "error" for event in events)


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
