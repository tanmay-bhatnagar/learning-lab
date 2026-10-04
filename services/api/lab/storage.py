"""Flat topic persistence. No user-supplied path is accepted."""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import uuid
from pathlib import Path
from typing import Any

from lab.contracts import FileRecord, Session

from .errors import CorruptData, Forbidden, InvalidInput, NotFound

ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def valid_id(value: str) -> str:
    if not ID.fullmatch(value):
        raise InvalidInput("Invalid ID: use lowercase letters, digits, hyphens or underscores.")
    return value


def checked(path: Path | str) -> Path:
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise Forbidden("Symlink paths are not allowed.")
    return path


def read_bytes(path: Path | str) -> bytes:
    checked(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise NotFound("File not found.") from None
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise Forbidden("Only regular files are allowed.")
        return stream.read()


def read_json(path: Path | str, default: Any = None) -> Any:
    checked(path)
    if not path.exists():
        return default
    try:
        return json.loads(read_bytes(path))
    except (ValueError, UnicodeError):
        raise CorruptData(f"Invalid saved data in {path.name}; restore a backup before retrying.") from None


def write_json(path: Path | str, data: Any) -> None:
    checked(path)
    temp = checked(path.parent / f".write-{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        checked(path)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_bytes(path: Path | str, data: bytes) -> None:
    checked(path)
    if not isinstance(data, bytes):
        raise TypeError("Stored artifact data must be bytes.")
    temp = checked(path.parent / f".write-{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        checked(path)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_text(path: Path | str, text: str) -> None:
    if not isinstance(text, str):
        raise TypeError("Stored artifact text must be a string.")
    write_bytes(path, text.encode("utf-8"))


def write_new_bytes(path: Path | str, data: bytes) -> None:
    """Durably create `path`; raise FileExistsError rather than replace an existing file."""
    checked(path)
    if not isinstance(data, bytes):
        raise TypeError("Stored artifact data must be bytes.")
    temp = checked(path.parent / f".write-{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        checked(path)
        # A hard link publishes the complete file atomically and, unlike os.replace, never overwrites.
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Store:
    def __init__(self, root: Path | str, settings: Path | str) -> None:
        self.root = checked(root)
        self.settings = checked(settings)
        self._conversation_lock = threading.Lock()

    def topic(self, topic: str) -> Path:
        path = checked(self.root / valid_id(topic))
        if not path.is_dir():
            raise NotFound("Topic not found.")
        metadata = read_json(path / "topic.json")
        if not metadata or metadata.get("archived"):
            raise NotFound("Topic not found.")
        return path

    def topics(self) -> list[dict[str, str]]:
        checked(self.root)
        if not self.root.exists():
            return []
        result = []
        for path in self.root.iterdir():
            if path.is_symlink() or not path.is_dir() or not ID.fullmatch(path.name):
                continue
            metadata = read_json(path / "topic.json")
            if metadata and not metadata.get("archived"):
                result.append({"id": path.name, "name": metadata["name"]})
        return sorted(result, key=lambda item: item["name"].casefold())

    def create(self, name: str) -> dict[str, str]:
        checked(self.root).mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:55] or "topic"
        topic = f"{slug}-{uuid.uuid4().hex[:12]}"
        path = checked(self.root / topic)
        path.mkdir()
        data = {"id": topic, "name": name}
        write_json(path / "topic.json", data)
        return data

    def files(self, topic: str) -> list[FileRecord]:
        return read_json(self.topic(topic) / "files.json", [])

    def file(self, topic: str, file_id: str) -> FileRecord:
        valid_id(file_id)
        for record in self.files(topic):
            if record["id"] == file_id:
                return record
        raise NotFound("Attachment not found in the selected topic.")

    def file_path(self, topic: str, name: str) -> Path:
        if not isinstance(name, str) or Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise Forbidden("Invalid stored filename.")
        return checked(self.topic(topic) / name)

    def _conversation_catalog(self, topic: str) -> list[dict[str, str]]:
        path = self.topic(topic) / "conversations.json"
        records = read_json(path)
        if records is None and not path.exists():
            records = [{"id": "default", "title": "Default"}]
        if not isinstance(records, list) or not all(
            isinstance(record, dict)
            and isinstance(record.get("id"), str)
            and ID.fullmatch(record["id"])
            and isinstance(record.get("title"), str)
            for record in records
        ):
            raise CorruptData("Invalid saved data in conversations.json; restore a backup before retrying.")
        ids = [record["id"] for record in records]
        if ids.count("default") != 1 or len(ids) != len(set(ids)):
            raise CorruptData("Invalid saved data in conversations.json; restore a backup before retrying.")
        for conversation_id in ids:
            if conversation_id != "default" and not (path.parent / f"conversation_{conversation_id}.json").is_file():
                raise CorruptData(
                    f"Missing saved conversation conversation_{conversation_id}.json; restore a backup before retrying."
                )
        for session_path in sorted(path.parent.glob("conversation_*.json")):
            conversation_id = session_path.stem.removeprefix("conversation_")
            if not ID.fullmatch(conversation_id) or conversation_id == "default" or conversation_id in ids:
                continue
            session = read_json(session_path)
            if not isinstance(session, dict) or not isinstance(session.get("messages"), list):
                raise CorruptData(f"Invalid saved data in {session_path.name}; restore a backup before retrying.")
            records.append({"id": conversation_id, "title": f"Recovered chat {conversation_id[:8]}"})
        if not path.exists() or len(records) != len(ids):
            write_json(path, records)
        return records

    def conversations(self, topic: str) -> list[dict[str, str]]:
        """List topic conversations, adding a catalog without changing legacy session bytes."""
        with self._conversation_lock:
            return [dict(record) for record in self._conversation_catalog(topic)]

    def conversation(self, topic: str, conversation_id: str) -> dict[str, str]:
        valid_id(conversation_id)
        for record in self.conversations(topic):
            if record["id"] == conversation_id:
                return record
        raise NotFound("Conversation not found in the selected topic.")

    def create_conversation(self, topic: str, title: str) -> dict[str, str]:
        title = self._conversation_title(title)
        with self._conversation_lock:
            records = self._conversation_catalog(topic)
            record = {"id": uuid.uuid4().hex, "title": title}
            path = self.topic(topic) / f"conversation_{record['id']}.json"
            write_new_bytes(path, b'{"messages": []}')
            write_json(self.topic(topic) / "conversations.json", [*records, record])
            return record

    def rename_conversation(self, topic: str, conversation_id: str, title: str) -> dict[str, str]:
        valid_id(conversation_id)
        title = self._conversation_title(title)
        with self._conversation_lock:
            records = self._conversation_catalog(topic)
            if not any(record["id"] == conversation_id for record in records):
                raise NotFound("Conversation not found in the selected topic.")
            updated = [{**record, "title": title} if record["id"] == conversation_id else record for record in records]
            write_json(self.topic(topic) / "conversations.json", updated)
            return {"id": conversation_id, "title": title}

    @staticmethod
    def _conversation_title(title: str) -> str:
        if (
            not isinstance(title, str)
            or not (title := title.strip())
            or len(title) > 120
            or any(ord(char) < 32 for char in title)
        ):
            raise InvalidInput("Conversation title must be 1–120 printable characters.")
        return title

    def session(self, topic: str, conversation_id: str = "default") -> Session:
        self.conversation(topic, conversation_id)
        name = "session.json" if conversation_id == "default" else f"conversation_{conversation_id}.json"
        path = self.topic(topic) / name
        if conversation_id != "default" and not path.exists():
            raise CorruptData(f"Missing saved conversation {name}; restore a backup before retrying.")
        return read_json(path, {"messages": []})

    def save_session(self, topic: str, session: Session, conversation_id: str = "default") -> None:
        self.conversation(topic, conversation_id)
        name = "session.json" if conversation_id == "default" else f"conversation_{conversation_id}.json"
        write_json(self.topic(topic) / name, session)
