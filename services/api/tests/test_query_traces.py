"""Topic-scoped query trace lifecycle and privacy contract."""

import asyncio
import json
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from lab.errors import CorruptData
from lab.query_traces import finalize, finalize_record, insert_started, list_traces, started_record, trace_path
from lab.storage import Store
from lab.web.app import create_app
from lab.web.locks import acquire_topic_lock
from tests.fakes import FakeModel


def payload(message="Explain", **updates):
    return {"message": message, "file_ids": [], "model": "fake", **updates}


class TraceStoreFaultModel(FakeModel):
    def __init__(self, trace_path, *, delete_database=False):
        super().__init__()
        self.trace_path = trace_path
        self.delete_database = delete_database

    async def stream_chat(self, messages, model, think, context_limit, context_metadata=None, *, generation_lock):
        self.calls.append(messages)
        async with generation_lock:
            yield {"type": "token", "text": "answer"}
            if self.delete_database:
                self.trace_path.unlink()
            else:
                with sqlite3.connect(self.trace_path) as connection:
                    connection.execute("DELETE FROM traces")
            yield {"type": "done", "model": model, "context": {"used": 10, "limit": context_limit}}


def test_default_and_named_chat_traces_are_topic_conversation_scoped(tmp_path):
    root = tmp_path / "Learning"
    client = TestClient(create_app(root, tmp_path / "state/settings.json", model_backend=FakeModel()))
    topic = client.post("/api/topics", json={"name": "Trace"}).json()["id"]
    conversation_id = client.post(f"/api/topics/{topic}/conversations", json={"title": "Named"}).json()["id"]

    assert client.post(f"/api/topics/{topic}/chat", json=payload("secret question")).status_code == 200
    assert (
        client.post(
            f"/api/topics/{topic}/conversations/{conversation_id}/chat", json=payload("another secret")
        ).status_code
        == 200
    )

    default_rows = client.get(f"/api/topics/{topic}/query-traces").json()["traces"]
    named_rows = client.get(f"/api/topics/{topic}/query-traces", params={"conversation_id": conversation_id}).json()[
        "traces"
    ]
    assert len(default_rows) == 2
    assert len(named_rows) == 1
    default = next(row for row in default_rows if row["conversation_id"] == "default")
    named = named_rows[0]
    assert default["status"] == named["status"] == "completed"
    assert default["conversation_id"] == "default"
    assert named["conversation_id"] == conversation_id
    assert default["user_saved"] and default["assistant_saved"]
    assert default["user_message_index"] == 0 and default["assistant_message_index"] == 1
    assert default["actual_model"] == "fake"
    assert "secret question" not in json.dumps(default)
    assert "reasoning" not in json.dumps(default)
    assert "answer" not in json.dumps(default)
    assert client.get(f"/api/topics/{topic}/query-traces", params={"conversation_id": "missing"}).status_code == 404
    assert client.get(f"/api/topics/{topic}/query-traces", params={"limit": 0}).status_code == 400


def test_busy_chat_is_recorded_as_rejected_before_acquiring_topic_lock(tmp_path):
    app = create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel())
    store = app.state.deps.store
    topic = store.create("Busy")["id"]

    async def hold_lock():
        return await acquire_topic_lock(app.state.deps.locks, topic)

    lease = asyncio.run(hold_lock())
    try:
        response = TestClient(app).post(f"/api/topics/{topic}/chat", json=payload())
    finally:
        lease.release()
    assert response.status_code == 409
    rows = TestClient(app).get(f"/api/topics/{topic}/query-traces").json()["traces"]
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"
    assert rows[0]["error"]["code"] == "topic_busy"
    assert rows[0]["user_saved"] is False


def test_missing_attachment_rejection_keeps_requested_ids_without_saving_user(tmp_path):
    client = TestClient(create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel()))
    topic = client.post("/api/topics", json={"name": "Missing attachment"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload(file_ids=["missing-file"]))
    assert response.status_code == 404
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["status"] == "rejected"
    assert trace["selected_file_ids"] == ["missing-file"]
    assert trace["user_saved"] is False


def test_chat_input_that_does_not_fit_is_recorded_as_rejected(tmp_path, monkeypatch):
    import lab.workflows.chat as chat_workflow

    from lab.errors import DoesNotFit

    def does_not_fit(*_args, **_kwargs):
        raise DoesNotFit("test preflight failure")

    monkeypatch.setattr(chat_workflow, "build_chat_prompt", does_not_fit)
    client = TestClient(create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel()))
    topic = client.post("/api/topics", json={"name": "Does not fit"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 422
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["status"] == "rejected"
    assert trace["user_saved"] is False


def test_generation_error_persists_error_and_session_indices(tmp_path):
    client = TestClient(
        create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel(fail=True))
    )
    topic = client.post("/api/topics", json={"name": "Error"}).json()["id"]
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert json.loads(response.text.splitlines()[-1])["type"] == "error"
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["status"] == "error"
    assert trace["error"]["code"] == "generation_failed"
    assert trace["user_saved"] and trace["assistant_saved"]
    assert trace["output_chars"] == len("answer")


def test_success_trace_records_cleanup_failure_without_relabeling_completion(tmp_path, caplog):
    class CloseFailureModel(FakeModel):
        async def stream_chat(self, messages, model, think, context_limit, context_metadata=None, *, generation_lock):
            self.calls.append(messages)
            async with generation_lock:
                try:
                    yield {"type": "token", "text": "answer"}
                    yield {"type": "done", "model": model, "context": {"used": 10, "limit": context_limit}}
                finally:
                    raise RuntimeError("cleanup detail")

    client = TestClient(
        create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=CloseFailureModel())
    )
    topic = client.post("/api/topics", json={"name": "Close"}).json()["id"]
    with caplog.at_level(logging.ERROR):
        response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert json.loads(response.text.splitlines()[-1])["type"] == "done"
    trace = client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]
    assert trace["status"] == "completed"
    assert trace["cleanup_error"]["code"] == "stream_close_failed"
    assert "cleanup detail" not in caplog.text


def test_final_trace_failure_is_logged_and_reported_before_done(tmp_path, monkeypatch, caplog):
    import lab.query_traces as query_traces_module

    def fail_finalize(*_args, **_kwargs):
        raise OSError("private database path")

    monkeypatch.setattr(query_traces_module, "finalize", fail_finalize)
    app = create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel())
    topic = app.state.deps.store.create("Trace write fault")["id"]
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 200
    assert "query trace could not be finalized" in response.text
    assert '"type": "done"' not in response.text
    assert "private database path" not in caplog.text
    assert "OSError" in caplog.text
    assert client.get(f"/api/topics/{topic}/messages").json()["messages"][-1]["content"] == "answer"
    assert client.get(f"/api/topics/{topic}/query-traces").json()["traces"][0]["status"] == "started"


def test_transient_trace_failure_is_not_retried_after_answer_save(tmp_path, monkeypatch, caplog):
    import lab.query_traces as query_traces_module

    original_finalize = query_traces_module.finalize
    attempts = 0

    def fail_once(path, record):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("transient database fault")
        return original_finalize(path, record)

    monkeypatch.setattr(query_traces_module, "finalize", fail_once)
    app = create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel())
    topic = app.state.deps.store.create("Transient trace fault")["id"]
    client = TestClient(app)
    with caplog.at_level(logging.ERROR):
        response = client.post(f"/api/topics/{topic}/chat", json=payload())

    assert attempts == 1
    assert "query trace could not be finalized" in response.text
    assert '"type": "done"' not in response.text
    assert "transient database fault" not in caplog.text
    assert "OSError" in caplog.text
    messages = client.get(f"/api/topics/{topic}/messages").json()["messages"]
    assert messages[-1]["content"] == "answer"
    assert "incomplete" not in messages[-1]
    assert not app.state.deps.locks[topic].locked()
    traces = client.get(f"/api/topics/{topic}/query-traces").json()["traces"]
    assert traces[0]["status"] == "started"
    assert traces[0]["actual_model"] is None


@pytest.mark.parametrize("delete_database", [False, True], ids=["delete-row", "delete-database"])
def test_lost_started_trace_is_reported_without_recreating_store(tmp_path, delete_database, caplog):
    root = tmp_path / "Learning"
    app = create_app(root, tmp_path / "state/settings.json", model_backend=FakeModel())
    topic = app.state.deps.store.create("Lost trace")["id"]
    path = root / topic / "query_traces.sqlite"
    model = TraceStoreFaultModel(path, delete_database=delete_database)
    app.state.deps.model_backend = model
    client = TestClient(app)

    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert "query trace could not be finalized" in response.text
    assert '"type": "done"' not in response.text
    assert client.get(f"/api/topics/{topic}/messages").json()["messages"][-1]["content"] == "answer"
    assert not client.get(f"/api/topics/{topic}/query-traces").json()["traces"]
    if delete_database:
        assert not path.exists()


def test_duplicate_trace_finalization_is_idempotent(tmp_path):
    store = Store(tmp_path / "Learning", tmp_path / "state/settings.json")
    topic = store.create("Idempotent trace")["id"]
    path = trace_path(store.topic(topic))
    started = started_record(
        topic_id=topic,
        conversation_id="default",
        message_chars=1,
        model="fake",
        think=None,
        context_limit=1024,
        embedding_model=None,
        retrieval_top_k=None,
        now="2026-10-03T00:00:00+00:00",
        trace_id="duplicate-trace",
    )
    insert_started(path, started)
    completed = finalize_record(
        started, status="completed", now="2026-10-03T00:00:01+00:00", stage="complete", total_ms=1
    )
    assert finalize(path, completed) is True
    assert finalize(path, completed) is False
    assert list_traces(path, conversation_id="default", limit=1)[0]["status"] == "completed"


def test_unfinished_started_trace_is_visible_after_interruption(tmp_path):
    store = Store(tmp_path / "Learning", tmp_path / "state/settings.json")
    topic = store.create("Interrupted")["id"]
    path = trace_path(store.topic(topic))
    record = started_record(
        topic_id=topic,
        conversation_id="default",
        message_chars=4,
        model="fake",
        think=None,
        context_limit=2048,
        embedding_model="embed",
        retrieval_top_k=6,
        now="2026-10-03T00:00:00+00:00",
        trace_id="trace-test",
    )
    insert_started(path, record)
    assert list_traces(path, conversation_id="default", limit=10) == [record]


def test_readonly_trace_uri_preserves_path_punctuation(tmp_path):
    store = Store(tmp_path / "Learning #? folder", tmp_path / "state/settings.json")
    topic = store.create("URI")["id"]
    path = trace_path(store.topic(topic))
    record = started_record(
        topic_id=topic,
        conversation_id="default",
        message_chars=4,
        model="fake",
        think=None,
        context_limit=2048,
        embedding_model="embed",
        retrieval_top_k=6,
        now="2026-10-03T00:00:00+00:00",
        trace_id="uri-test",
    )
    insert_started(path, record)
    assert list_traces(path, conversation_id=None, limit=10) == [record]
    assert not path.with_name("query_traces.sqlite?mode=ro").exists()


def test_trace_schema_version_rejects_newer_database(tmp_path):
    store = Store(tmp_path / "Learning", tmp_path / "state/settings.json")
    topic = store.create("Schema")["id"]
    path = trace_path(store.topic(topic))
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(CorruptData, match="Unsupported query trace schema"):
        list_traces(path, conversation_id="default", limit=10)


@pytest.mark.parametrize(
    "table_sql",
    [
        None,
        "CREATE TABLE traces (id TEXT NOT NULL, conversation_id TEXT NOT NULL, started_at TEXT NOT NULL, "
        "status TEXT NOT NULL, record_json TEXT NOT NULL)",
    ],
    ids=["missing-table", "missing-primary-key"],
)
def test_malformed_version_one_schema_is_rejected_without_mutation(tmp_path, table_sql):
    model = FakeModel()
    client = TestClient(create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=model))
    topic = client.post("/api/topics", json={"name": "Malformed schema"}).json()["id"]
    path = tmp_path / "Learning" / topic / "query_traces.sqlite"
    with sqlite3.connect(path) as connection:
        if table_sql is not None:
            connection.execute(table_sql)
        connection.execute("PRAGMA user_version = 1")
    original = path.read_bytes()

    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 500
    assert path.read_bytes() == original
    assert client.get(f"/api/topics/{topic}/messages").json() == {"messages": []}
    assert model.calls == []


def test_trace_database_symlink_is_rejected(tmp_path):
    store = Store(tmp_path / "Learning", tmp_path / "state/settings.json")
    topic = store.create("Symlink")["id"]
    trace = trace_path(store.topic(topic))
    outside = tmp_path / "outside.sqlite"
    outside.touch()
    trace.symlink_to(outside)
    client = TestClient(create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=FakeModel()))
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 403
    assert sqlite3.connect(outside).execute("SELECT name FROM sqlite_master").fetchall() == []


def test_trace_initialization_failure_precedes_history_and_model_mutation(tmp_path):
    model = FakeModel()
    client = TestClient(create_app(tmp_path / "Learning", tmp_path / "state/settings.json", model_backend=model))
    topic = client.post("/api/topics", json={"name": "Trace init"}).json()["id"]
    (tmp_path / "Learning" / topic / "query_traces.sqlite").mkdir()
    response = client.post(f"/api/topics/{topic}/chat", json=payload())
    assert response.status_code == 500
    assert client.get(f"/api/topics/{topic}/messages").json() == {"messages": []}
    assert model.calls == []


def test_non_sqlite_trace_file_maps_to_corrupt_data(tmp_path):
    store = Store(tmp_path / "Learning", tmp_path / "state/settings.json")
    topic = store.create("Corrupt trace")["id"]
    path = trace_path(store.topic(topic))
    path.write_bytes(b"not a SQLite database")
    with pytest.raises(CorruptData, match="query trace database"):
        insert_started(
            path,
            started_record(
                topic_id=topic,
                conversation_id="default",
                message_chars=1,
                model="fake",
                think=None,
                context_limit=1024,
                embedding_model=None,
                retrieval_top_k=None,
                now="2026-10-03T00:00:00+00:00",
                trace_id="bad-db",
            ),
        )
