"""Stored JSON written through typed contracts matches legacy shapes."""

from __future__ import annotations

import json
from pathlib import Path

from lab.contracts import FileRecord, Session, TopicRecord
from lab.storage import write_json


def test_typed_records_match_fixture_json_shapes(tmp_path: Path):
    topic: TopicRecord = {"id": "demo-topic", "name": "Demo", "learning_goal": "Learn things"}
    file_record: FileRecord = {
        "id": "abc12345678901234567890123456789012",
        "name": "paper.pdf",
        "original_name": "2026_01_01_paper-abc12345678901234567890123456789012.pdf",
        "status": "ready",
        "parser": "docling",
        "index_status": "ready",
        "index_mode": "keyword",
    }
    session: Session = {
        "messages": [{"role": "user", "content": "Hello", "file_ids": []}],
        "context": {"used": 1, "limit": 32768, "estimated": True, "truncated_messages": 0},
    }
    topic_path = tmp_path / "topic.json"
    files_path = tmp_path / "files.json"
    session_path = tmp_path / "session.json"
    write_json(topic_path, topic)
    write_json(files_path, [file_record])
    write_json(session_path, session)
    assert json.loads(topic_path.read_text())["name"] == "Demo"
    assert json.loads(files_path.read_text())[0]["status"] == "ready"
    assert json.loads(session_path.read_text())["messages"][0]["role"] == "user"
