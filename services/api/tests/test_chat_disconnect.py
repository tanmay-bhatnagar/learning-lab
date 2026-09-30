"""Chat must release its topic lock however the client disconnects."""
import asyncio
import gc
import json

import pytest
from fastapi.testclient import TestClient

from lab.main import create_app


class FakeModel:
    async def list_models(self):
        return {"models": [{"id": "fake"}]}

    async def stream_chat(self, messages, model, think, context_limit):
        yield {"type": "token", "text": "answer"}
        yield {"type": "done", "context": {"used": 1, "limit": context_limit,
                                           "estimated": True, "truncated_messages": 0}}


def _scope(topic, body, spec_version):
    return {
        "type": "http", "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": f"/api/topics/{topic}/chat", "raw_path": f"/api/topics/{topic}/chat".encode(),
        "query_string": b"", "root_path": "",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
    }


async def _disconnected_chat(app, topic, spec_version):
    body = json.dumps({"message": "Explain", "file_ids": [], "model": "fake"}).encode()
    pending = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            raise OSError("client went away")

    # Cleanup must not depend on the cyclic garbage collector finalizing an abandoned generator.
    gc.disable()
    try:
        await app(_scope(topic, body, spec_version), receive, send)
    except Exception:
        pass
    finally:
        await asyncio.sleep(0)
        gc.enable()


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
@pytest.mark.parametrize("http_middleware", [True, False])
def test_disconnect_before_streaming_releases_topic_lock(tmp_path, spec_version, http_middleware):
    app = create_app(tmp_path.resolve() / "Learning", tmp_path.resolve() / "state/settings.json",
                     model_backend=FakeModel())
    if not http_middleware:
        app.user_middleware = [item for item in app.user_middleware
                               if item.cls.__name__ != "BaseHTTPMiddleware"]
    topic = app.state.store.create("Disconnect")["id"]
    asyncio.run(_disconnected_chat(app, topic, spec_version))
    client = TestClient(app)
    response = client.post(f"/api/topics/{topic}/chat",
                           json={"message": "Again", "file_ids": [], "model": "fake"})
    assert response.status_code == 200, response.text
    messages = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1].get("incomplete") is True
    assert messages[-1]["content"] == "answer"
