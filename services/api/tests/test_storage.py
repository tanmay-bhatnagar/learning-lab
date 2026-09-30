import os

import pytest

from lab import storage
from lab.storage import write_new_bytes


def test_write_new_bytes_creates_once_and_never_overwrites(tmp_path):
    path = tmp_path.resolve() / "original.pdf"
    write_new_bytes(path, b"%PDF-1.7 first")
    with pytest.raises(FileExistsError):
        write_new_bytes(path, b"%PDF-1.7 second")
    assert path.read_bytes() == b"%PDF-1.7 first"
    assert [item.name for item in path.parent.iterdir()] == ["original.pdf"]


def test_write_new_bytes_leaves_no_partial_file_when_the_write_fails(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "original.pdf"

    def fail(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "fsync", fail)
    with pytest.raises(OSError, match="disk full"):
        write_new_bytes(path, b"%PDF-1.7 data")
    monkeypatch.setattr(storage.os, "fsync", os.fsync)
    assert list(path.parent.iterdir()) == []


def test_write_new_bytes_rejects_non_bytes(tmp_path):
    with pytest.raises(TypeError):
        write_new_bytes(tmp_path.resolve() / "original.pdf", "text")
