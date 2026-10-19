"""Streaming disconnect and response-finalization contracts."""

from __future__ import annotations

import asyncio
import json

import pytest
from starlette.requests import ClientDisconnect

from lab.web.middleware import FinalizedStreamingResponse
from tests.test_evidence_chat import _app, _chat_scope, _retriever, _topic_with_index


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
@pytest.mark.parametrize("http_middleware", [True, False])
def test_disconnect_during_silent_initial_provider_cancels_and_saves_empty_incomplete_turn(
    tmp_path, spec_version, http_middleware
):
    entered = asyncio.Event()
    closed = asyncio.Event()

    class SilentFirstModel:
        def __init__(self):
            self.calls = []

        async def list_models(self):
            return {"models": [{"id": "local", "vision": False}]}

        async def embed_texts(self, texts, model, *, generation_lock):
            async with generation_lock:
                return [[0.1] for _ in texts]

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
            self.calls.append(messages)

            async def stream():
                async with generation_lock:
                    try:
                        yield {"type": "token", "text": "{"}
                        entered.set()
                        await asyncio.Event().wait()
                    finally:
                        closed.set()

            return stream()

    model = SilentFirstModel()
    app = _app(tmp_path, model)
    app.state.deps.retriever = _retriever([])
    if not http_middleware:
        app.user_middleware = [item for item in app.user_middleware if item.cls.__name__ != "BaseHTTPMiddleware"]
    client = _topic_client = None

    async def scenario():
        nonlocal client, _topic_client
        from fastapi.testclient import TestClient

        client = TestClient(app)
        topic, record = _topic_with_index(client)
        body = json.dumps(
            {"message": "Question", "file_ids": [record["id"]], "model": "local", "extra_search": True}
        ).encode()
        pending = [{"type": "http.request", "body": body, "more_body": False}]
        disconnected = False

        async def receive():
            nonlocal disconnected
            if pending:
                return pending.pop(0)
            if not disconnected:
                await entered.wait()
                disconnected = True
                return {"type": "http.disconnect"}
            await asyncio.Event().wait()

        async def send(_message):
            return None

        task = asyncio.create_task(app(_chat_scope(topic, body, spec_version), receive, send))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            await asyncio.wait_for(asyncio.shield(task), timeout=1)
            assert closed.is_set()
            assert not app.state.deps.locks[topic].locked()
            messages = client.get(f"/api/topics/{topic}/messages").json()["messages"]
            assistant = messages[-1]
            assert assistant["role"] == "assistant"
            assert assistant["content"] == ""
            assert assistant["incomplete"] is True
            assert assistant["retrieval"]["evidence_search"]["outcome"] == "cancelled"
            assert assistant["retrieval"]["evidence_search"]["generation_count"] == 1
            assert assistant["retrieval"]["evidence_search"]["initial_chunk_ids"]
        finally:
            if not task.done():
                task.cancel()
            try:
                await asyncio.wait_for(task, timeout=1)
            except BaseException:  # noqa: BLE001 - the test asserts response cleanup after cancellation.
                pass
            _topic_client = client

    try:
        asyncio.run(scenario())
    finally:
        if _topic_client is not None:
            _topic_client.close()


def test_finalized_response_completion_orders_background_before_close_once():
    calls = []

    async def content():
        try:
            yield "answer"
        finally:
            calls.append("iterator_closed")

    async def background():
        calls.append("background")

    async def on_close():
        calls.append("on_close")

    response = FinalizedStreamingResponse(content(), on_close=on_close, background=background)
    sent = []

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    async def scenario():
        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"}, "method": "GET", "path": "/"},
            receive,
            send,
        )

    asyncio.run(scenario())

    assert [message["type"] for message in sent] == [
        "http.response.start",
        "http.response.body",
        "http.response.body",
    ]
    assert calls == ["iterator_closed", "background", "on_close"]


@pytest.mark.parametrize("failure", ["send", "provider"])
def test_finalized_response_failure_skips_background_and_closes_once(failure):
    calls = []

    class Content:
        def __aiter__(self):
            return self

        async def __anext__(self):
            if failure == "provider":
                raise RuntimeError("synthetic provider failure")
            return "unused"

        async def aclose(self):
            calls.append("iterator_closed")

    async def background():
        calls.append("background")

    async def on_close():
        calls.append("on_close")

    response = FinalizedStreamingResponse(Content(), on_close=on_close, background=background)

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        if failure == "send" and message["type"] == "http.response.start":
            raise OSError("synthetic disconnect")

    async def scenario():
        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"}, "method": "GET", "path": "/"},
            receive,
            send,
        )

    with pytest.raises(ClientDisconnect if failure == "send" else RuntimeError):
        asyncio.run(scenario())

    assert calls == ["iterator_closed", "on_close"]
