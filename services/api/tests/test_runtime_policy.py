from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lab.chat_prompt import SYSTEM_RULES, build_chat_prompt
from lab.config import DEFAULT_RUNTIME_POLICY_PATH, load_config
from lab.errors import DoesNotFit, RuntimePolicyUnavailable
from lab.runtime_policy import load_runtime_policy
from lab.web.app import create_app
from tests.fakes import FakeModel


def test_runtime_policy_config_default_is_independent_of_learning_root(monkeypatch, tmp_path):
    monkeypatch.delenv("LEARNING_LAB_POLICY_PATH", raising=False)
    config = load_config(learning_root=tmp_path / "Learning")

    assert config.runtime_policy_path == DEFAULT_RUNTIME_POLICY_PATH.resolve()
    assert config.runtime_policy_path != config.learning_root / "AGENTS.md"


def test_runtime_policy_environment_and_explicit_override_precedence(monkeypatch, tmp_path):
    environment_path = tmp_path / "environment-policy.md"
    explicit_path = tmp_path / "explicit-policy.md"
    monkeypatch.setenv("LEARNING_LAB_POLICY_PATH", str(environment_path))

    assert load_config().runtime_policy_path == environment_path.resolve()
    assert load_config(runtime_policy_path=explicit_path).runtime_policy_path == explicit_path.resolve()
    app = create_app(tmp_path / "Learning", tmp_path / "settings.json", runtime_policy_path=explicit_path)
    assert app.state.deps.config.runtime_policy_path == explicit_path.resolve()


@pytest.mark.parametrize("content", ["", " \n\t"])
def test_runtime_policy_rejects_empty_content(tmp_path, content):
    path = tmp_path / "policy.md"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(RuntimePolicyUnavailable, match="policy is empty"):
        load_runtime_policy(path)


@pytest.mark.parametrize("state", ["missing", "invalid_utf8", "directory", "permission"])
def test_runtime_policy_rejects_unreadable_content(tmp_path, state, monkeypatch):
    path = tmp_path / "policy.md"
    if state == "invalid_utf8":
        path.write_bytes(b"\xff\xfe")
    elif state == "directory":
        path.mkdir()
    elif state == "permission":
        original_read_text = Path.read_text

        def permission_error(self, *args, **kwargs):
            if self == path:
                raise PermissionError("private diagnostic")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", permission_error)

    with pytest.raises(RuntimePolicyUnavailable, match="policy is unavailable"):
        load_runtime_policy(path)


def test_runtime_policy_loads_full_file_without_trimming(tmp_path):
    policy = "runtime policy line\n" * 400
    path = tmp_path / "policy.md"
    path.write_text(policy, encoding="utf-8")

    assert load_runtime_policy(path) == policy


def test_full_runtime_policy_is_preserved_in_system_message_or_rejected_as_unfit():
    policy = "Policy detail. " * 500
    kwargs = {
        "history": [],
        "evidence": [],
        "citations": [],
        "attachments": [],
        "question": "What is a system?",
        "active_topic": "synthetic-topic-id",
        "learning_goal": "",
        "runtime_policy": policy,
        "retrieval_record": {},
    }

    with pytest.raises(DoesNotFit):
        build_chat_prompt(**kwargs, context_limit=8192)
    for context_limit in (16384, 32768):
        plan = build_chat_prompt(**kwargs, context_limit=context_limit)
        system = plan["prompt"][0]["content"]
        assert system.startswith(SYSTEM_RULES)
        assert "App-selected topic ID synthetic-topic-id" in system
        assert "Learning/synthetic-topic-id/" in system
        assert f"<runtime-policy>\n{policy}\n</runtime-policy>" in system


@pytest.mark.parametrize("route", ["default", "conversation"])
@pytest.mark.parametrize("failure", ["missing", "empty", "invalid_utf8"])
def test_policy_load_failure_precedes_retrieval_save_and_model_and_releases_lock(tmp_path, route, failure):
    policy_path = tmp_path / "runtime-policy.md"
    if failure == "empty":
        policy_path.write_text(" \n", encoding="utf-8")
    elif failure == "invalid_utf8":
        policy_path.write_bytes(b"\xff")
    else:
        policy_path.unlink(missing_ok=True)
    model = FakeModel()
    retriever_calls = []

    async def retriever(*_args, **_kwargs):
        retriever_calls.append(True)
        return {"hits": [], "mode": "keyword"}

    from tests.test_retrieval_api import fake_structured_parser

    app = create_app(
        tmp_path / "Learning",
        tmp_path / "settings.json",
        model_backend=model,
        retriever=retriever,
        structured_parser=fake_structured_parser,
        runtime_policy_path=policy_path,
    )
    client = TestClient(app)
    topic = client.post("/api/topics", json={"name": "Runtime policy"}).json()["id"]
    other_topic = client.post("/api/topics", json={"name": "Other topic"}).json()["id"]
    attachment = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("notes.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    assert attachment["index_status"] == "ready"
    original_prompt = {
        "message": "Explain this topic",
        "file_ids": [attachment["id"]],
        "model": "fake",
        "think": True,
    }
    if route == "default":
        url = f"/api/topics/{topic}/chat"
    else:
        conversation = client.post(f"/api/topics/{topic}/conversations", json={"title": "Test"}).json()
        url = f"/api/topics/{topic}/conversations/{conversation['id']}/chat"

    response = client.post(url, json=original_prompt)

    assert response.status_code == 500
    assert "runtime policy" in response.text.lower()
    assert "Explain this topic" not in response.text
    assert policy_path.as_posix() not in response.text
    assert retriever_calls == []
    assert model.calls == []
    messages_url = url.rsplit("/chat", 1)[0]
    saved = (
        client.get(f"{messages_url}/messages")
        if route == "conversation"
        else client.get(f"/api/topics/{topic}/messages")
    )
    assert saved.status_code == 200
    assert saved.json()["messages"] == []
    trace_response = client.get(f"/api/topics/{topic}/query-traces")
    trace = trace_response.json()["traces"][0]
    assert trace["status"] == "error"
    assert trace["stage"] == "preflight"
    assert trace["error"]["exception_type"] == "RuntimePolicyUnavailable"
    assert policy_path.as_posix() not in json.dumps(trace["error"])

    repaired_policy = "repaired policy version with unique text"
    policy_path.write_text(repaired_policy, encoding="utf-8")
    retry = client.post(url, json={**original_prompt, "model": "selected-model"})
    assert retry.status_code == 200
    assert model.calls
    assert "<runtime-policy>\n" + repaired_policy + "\n</runtime-policy>" in model.calls[-1][0]["content"]
    system = model.calls[-1][0]["content"]
    assert system.startswith(SYSTEM_RULES)
    assert f"App-selected topic ID {topic}" in system
    assert f"Learning/{topic}/" in system
    assert other_topic not in system
    assert str((tmp_path / "Learning" / topic).resolve()) not in system


def test_full_policy_budget_rejection_does_not_save_or_call_model(tmp_path):
    policy_path = tmp_path / "runtime-policy.md"
    policy = "Policy detail. " * 500
    policy_path.write_text(policy, encoding="utf-8")
    model = FakeModel()
    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "settings.json",
            model_backend=model,
            runtime_policy_path=policy_path,
        )
    )
    topic = client.post("/api/topics", json={"name": "Budget"}).json()["id"]

    response = client.post(
        f"/api/topics/{topic}/chat",
        json={
            "message": "What is a system?",
            "file_ids": [],
            "model": "fake",
            "think": True,
            "context_limit": 8192,
        },
    )

    assert response.status_code == 422
    assert "context limit" in response.text
    assert model.calls == []
    assert client.get(f"/api/topics/{topic}/messages").json()["messages"] == []
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["status"] == "rejected"
    assert trace["stage"] == "preflight"
