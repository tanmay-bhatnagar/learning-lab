"""Live Ollama smoke on an isolated temp root; skipped when the service is unavailable."""

from __future__ import annotations

import httpx
import pytest

from lab.http.app import create_app


def _ollama_ready() -> bool:
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=2)
        response.raise_for_status()
        names = {item.get("name") or item.get("model") for item in response.json().get("models", [])}
        return "qwen3.5:4b-q8_0" in names
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _ollama_ready(), reason="Ollama or qwen3.5:4b-q8_0 unavailable")
def test_live_chat_stream_on_isolated_root(tmp_path):
    root = tmp_path / "Learning"
    state = tmp_path / "state"
    state.mkdir()
    settings = state / "settings.json"
    settings.write_text('{"model":"qwen3.5:4b-q8_0","embedding_model":"nomic-embed-text"}')
    app = create_app(root, settings)
    topic = app.state.deps.store.create("Live smoke")["id"]

    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        f"/api/topics/{topic}/chat",
        json={"message": "Reply with exactly: pong", "model": "qwen3.5:4b-q8_0", "think": False},
    )
    assert response.status_code == 200
    import json

    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[-1]["type"] == "done"
    saved = client.get(f"/api/topics/{topic}/messages").json()
    assert saved["messages"][-1]["role"] == "assistant"
    assert "pong" in saved["messages"][-1]["content"].lower()
