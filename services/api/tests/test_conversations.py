"""Independent topic conversations and legacy compatibility."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from lab.errors import CorruptData
from lab.storage import Store
from lab.web.app import create_app
from lab.web.locks import acquire_topic_lock
from tests.fakes import FakeModel


def test_catalog_migration_persistence_and_topic_isolation(tmp_path):
    root = tmp_path / "Learning"
    client = TestClient(create_app(root, tmp_path / "state/settings.json", model_backend=FakeModel()))
    first = client.post("/api/topics", json={"name": "First"}).json()["id"]
    second = client.post("/api/topics", json={"name": "Second"}).json()["id"]
    legacy = root / first / "session.json"
    original = b'{"messages": [{"role": "user", "content": "legacy"}]}\n'
    legacy.write_bytes(original)
    base = f"/api/topics/{first}/conversations"
    assert client.get(base).json() == {"conversations": [{"id": "default", "title": "Default"}]}
    assert client.get(base).json()["conversations"][0]["id"] == "default"
    assert legacy.read_bytes() == original
    created = client.post(base, json={"title": "  New path  "}).json()
    assert created["title"] == "New path"
    assert (root / first / f"conversation_{created['id']}.json").is_file()
    assert client.patch(f"{base}/{created['id']}", json={"title": "Renamed"}).json() == {
        "id": created["id"],
        "title": "Renamed",
    }
    assert client.get(f"{base}/{created['id']}/messages").json() == {"messages": []}
    assert client.get(f"/api/topics/{second}/conversations/{created['id']}/messages").status_code == 404
    assert (
        client.post(
            f"/api/topics/{second}/conversations/{created['id']}/chat",
            json={"message": "Wrong topic", "file_ids": [], "model": "fake"},
        ).status_code
        == 404
    )
    assert client.patch(f"/api/topics/{second}/conversations/{created['id']}", json={"title": "No"}).status_code == 404
    assert client.get(f"{base}/default/messages").json() == client.get(f"/api/topics/{first}/messages").json()
    restarted = TestClient(create_app(root, tmp_path / "state/settings.json", model_backend=FakeModel()))
    assert restarted.get(base).json()["conversations"][-1] == {"id": created["id"], "title": "Renamed"}
    assert legacy.read_bytes() == original


def test_new_chat_has_independent_history_and_saved_retrieval(tmp_path):
    model = FakeModel()
    client = TestClient(create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=model))
    topic = client.post("/api/topics", json={"name": "Chat"}).json()["id"]
    base = f"/api/topics/{topic}/conversations"
    one = client.post(base, json={"title": "One"}).json()["id"]
    two = client.post(base, json={"title": "Two"}).json()["id"]
    payload = {"message": "First", "file_ids": [], "model": "fake"}
    response = client.post(f"{base}/{one}/chat", json=payload)
    assert response.status_code == 200
    done = [json.loads(line) for line in response.text.splitlines() if line][-1]
    assert done["type"] == "done"
    saved = client.get(f"{base}/{one}/messages").json()["messages"]
    assert saved[-1]["retrieval"] == done["retrieval"]
    assert saved[-1]["retrieval"]["citations"] == []
    assert client.get(f"{base}/{two}/messages").json() == {"messages": []}
    assert client.get(f"{base}/default/messages").json() == {"messages": []}
    assert client.post(f"{base}/{two}/chat", json={**payload, "message": "Second"}).status_code == 200
    assert model.calls[-1][-1]["content"] == "Second"
    assert all(message.get("content") != "First" for message in model.calls[-1])


def test_missing_catalog_recovers_saved_conversations_without_rewriting_history(tmp_path):
    root = tmp_path / "Learning"
    client = TestClient(create_app(root, tmp_path / "state/settings.json", model_backend=FakeModel()))
    topic = client.post("/api/topics", json={"name": "Recovery"}).json()["id"]
    base = f"/api/topics/{topic}/conversations"
    created = client.post(base, json={"title": "Original title"}).json()
    saved_path = root / topic / f"conversation_{created['id']}.json"
    saved_path.write_text('{"messages": [{"role": "user", "content": "Keep me"}]}')
    before = saved_path.read_bytes()
    (root / topic / "conversations.json").unlink()
    recovered = client.get(base).json()["conversations"]
    assert recovered == [
        {"id": "default", "title": "Default"},
        {"id": created["id"], "title": f"Recovered chat {created['id'][:8]}"},
    ]
    assert client.get(f"{base}/{created['id']}/messages").json()["messages"][0]["content"] == "Keep me"
    assert saved_path.read_bytes() == before
    assert client.get(base).json()["conversations"] == recovered


def test_existing_catalog_recovers_orphan_without_rewriting_sessions(tmp_path):
    root = tmp_path / "Learning"
    client = TestClient(create_app(root, tmp_path / "state/settings.json", model_backend=FakeModel()))
    topic = client.post("/api/topics", json={"name": "Recovery"}).json()["id"]
    base = f"/api/topics/{topic}/conversations"
    assert client.get(base).status_code == 200
    legacy = root / topic / "session.json"
    legacy_bytes = b'{"messages": [{"role": "user", "content": "legacy"}]}\n'
    legacy.write_bytes(legacy_bytes)
    orphan = root / topic / "conversation_orphan.json"
    orphan_bytes = b'{"messages": [{"role": "user", "content": "orphan"}]}\n'
    orphan.write_bytes(orphan_bytes)

    expected = [{"id": "default", "title": "Default"}, {"id": "orphan", "title": "Recovered chat orphan"}]
    assert client.get(base).json() == {"conversations": expected}
    assert json.loads((root / topic / "conversations.json").read_text()) == expected
    assert client.get(f"{base}/orphan/messages").json()["messages"][0]["content"] == "orphan"
    assert legacy.read_bytes() == legacy_bytes
    assert orphan.read_bytes() == orphan_bytes


@pytest.mark.parametrize(
    "records",
    [
        [],
        [{"id": "default", "title": "Default"}, {"id": "default", "title": "Again"}],
        [{"id": "default", "title": "Default"}, {"id": "Bad ID", "title": "Bad"}],
        [{"id": "default", "title": "Default"}, {"id": "missing", "title": "Missing"}],
        None,
    ],
)
def test_corrupt_catalog_is_not_rewritten(tmp_path, records):
    store = Store(tmp_path / "Learning", tmp_path / "state/settings.json")
    topic = store.create("Corrupt")["id"]
    catalog = store.topic(topic) / "conversations.json"
    catalog.write_text(json.dumps(records))
    before = catalog.read_bytes()

    with pytest.raises(CorruptData):
        store.conversations(topic)
    assert catalog.read_bytes() == before


@pytest.mark.parametrize("conversation_id", ["default", "separate"])
def test_messages_wait_for_pending_chat_finalization(tmp_path, conversation_id):
    app = create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel())
    store = app.state.deps.store
    topic = store.create("Pending chat")["id"]
    if conversation_id != "default":
        store.create_conversation(topic, "Separate")
        records = store.conversations(topic)
        conversation_id = records[-1]["id"]
    store.save_session(topic, {"messages": [{"role": "user", "content": "Question"}]}, conversation_id)

    async def exercise():
        lease = await acquire_topic_lock(app.state.deps.locks, topic)
        url = (
            f"/api/topics/{topic}/messages"
            if conversation_id == "default"
            else f"/api/topics/{topic}/conversations/{conversation_id}/messages"
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            pending = asyncio.create_task(client.get(url))
            try:
                await asyncio.sleep(0.02)
                assert not pending.done()
                store.save_session(
                    topic,
                    {
                        "messages": [
                            {"role": "user", "content": "Question"},
                            {"role": "assistant", "content": "Partial", "incomplete": True},
                        ]
                    },
                    conversation_id,
                )
            finally:
                lease.release()
            response = await asyncio.wait_for(pending, timeout=1)
            assert response.status_code == 200
            assert response.json()["messages"][-1] == {
                "role": "assistant",
                "content": "Partial",
                "incomplete": True,
            }

    asyncio.run(exercise())


def test_interrupted_stream_is_saved_only_to_selected_conversation(tmp_path):
    client = TestClient(
        create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel(fail=True))
    )
    topic = client.post("/api/topics", json={"name": "Interrupted"}).json()["id"]
    base = f"/api/topics/{topic}/conversations"
    target = client.post(base, json={"title": "Interrupted"}).json()["id"]
    response = client.post(f"{base}/{target}/chat", json={"message": "Explain", "file_ids": [], "model": "fake"})
    assert json.loads(response.text.splitlines()[-1])["type"] == "error"
    messages = client.get(f"{base}/{target}/messages").json()["messages"]
    assert messages[-1]["content"] == "answer"
    assert messages[-1]["incomplete"] is True
    assert messages[-1]["retrieval"]["citations"] == []
    assert client.get(f"{base}/default/messages").json() == {"messages": []}


def test_conversation_citations_match_saved_answer(tmp_path):
    from tests.test_retrieval_api import fake_structured_parser

    async def retriever(store, topic, query, **kwargs):
        return {
            "mode": "keyword",
            "hits": [
                {
                    "chunk_id": "cited-one",
                    "file_id": kwargs["file_ids"][0],
                    "file_name": "paper.pdf",
                    "text": "Grounded evidence.",
                    "headings": [],
                    "pages": [1],
                    "bboxes": [],
                    "asset_ids": [],
                    "trace": {"keyword": {"rank": 1, "score": 1.0}},
                }
            ],
        }

    client = TestClient(
        create_app(
            tmp_path / "Learning",
            tmp_path / "state/settings.json",
            model_backend=FakeModel(),
            structured_parser=fake_structured_parser,
            retriever=retriever,
        )
    )
    topic = client.post("/api/topics", json={"name": "Citations"}).json()["id"]
    file_record = client.post(
        f"/api/topics/{topic}/files",
        files={"file": ("paper.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"parser": "docling"},
    ).json()
    base = f"/api/topics/{topic}/conversations"
    target = client.post(base, json={"title": "Evidence"}).json()["id"]
    response = client.post(
        f"{base}/{target}/chat",
        json={"message": "Explain", "file_ids": [file_record["id"]], "model": "fake"},
    )
    assert response.status_code == 200
    done = json.loads(response.text.splitlines()[-1])
    saved = client.get(f"{base}/{target}/messages").json()["messages"][-1]
    assert [citation["chunk_id"] for citation in done["retrieval"]["citations"]] == ["cited-one"]
    assert saved["retrieval"] == done["retrieval"]
