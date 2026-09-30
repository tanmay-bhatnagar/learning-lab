"""Flat topic persistence. No user-supplied path is accepted."""

import json
import os
import re
import stat
import uuid
from pathlib import Path

from .errors import CorruptData, Forbidden, InvalidInput, NotFound

ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def valid_id(value):
    if not ID.fullmatch(value):
        raise InvalidInput("Invalid ID: use lowercase letters, digits, hyphens or underscores.")
    return value


def checked(path):
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise Forbidden("Symlink paths are not allowed.")
    return path


def read_bytes(path):
    checked(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise NotFound("File not found.") from None
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise Forbidden("Only regular files are allowed.")
        return stream.read()


def read_json(path, default=None):
    checked(path)
    if not path.exists():
        return default
    try:
        return json.loads(read_bytes(path))
    except (ValueError, UnicodeError):
        raise CorruptData(f"Invalid saved data in {path.name}; restore a backup before retrying.") from None


def write_json(path, data):
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


def write_bytes(path, data):
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


def write_text(path, text):
    if not isinstance(text, str):
        raise TypeError("Stored artifact text must be a string.")
    write_bytes(path, text.encode("utf-8"))


def write_new_bytes(path, data):
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
    def __init__(self, root, settings):
        self.root = checked(root)
        self.settings = checked(settings)

    def topic(self, topic):
        path = checked(self.root / valid_id(topic))
        if not path.is_dir():
            raise NotFound("Topic not found.")
        metadata = read_json(path / "topic.json")
        if not metadata or metadata.get("archived"):
            raise NotFound("Topic not found.")
        return path

    def topics(self):
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

    def create(self, name):
        checked(self.root).mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:55] or "topic"
        topic = f"{slug}-{uuid.uuid4().hex[:12]}"
        path = checked(self.root / topic)
        path.mkdir()
        data = {"id": topic, "name": name}
        write_json(path / "topic.json", data)
        return data

    def files(self, topic):
        return read_json(self.topic(topic) / "files.json", [])

    def file(self, topic, file_id):
        valid_id(file_id)
        for record in self.files(topic):
            if record["id"] == file_id:
                return record
        raise NotFound("Attachment not found in the selected topic.")

    def file_path(self, topic, name):
        if not isinstance(name, str) or Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise Forbidden("Invalid stored filename.")
        return checked(self.topic(topic) / name)

    def session(self, topic):
        return read_json(self.topic(topic) / "session.json", {"messages": []})

    def save_session(self, topic, session):
        write_json(self.topic(topic) / "session.json", session)
