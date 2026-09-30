"""Configuration and import side-effect tests."""

import importlib
import sys


def test_import_main_does_not_create_app_or_read_environment(monkeypatch):
    monkeypatch.delenv("LEARNING_LAB_ROOT", raising=False)
    monkeypatch.delenv("LEARNING_LAB_STATE_ROOT", raising=False)
    monkeypatch.delenv("LEARNING_LAB_SETTINGS", raising=False)
    monkeypatch.delenv("LEARNING_LAB_MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    sys.modules.pop("lab.main", None)
    module = importlib.import_module("lab.main")
    assert not hasattr(module, "app") or module.__dict__.get("app") is None
    assert callable(module.create_app)


def test_create_app_explicit_args_override_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LEARNING_LAB_ROOT", "/should/not/be/used")
    from lab.main import create_app

    root = tmp_path / "Learning"
    settings = tmp_path / "settings.json"
    app = create_app(root, settings, max_upload_bytes=12345)
    assert app.state.deps.store.root == root.resolve()
    assert app.state.deps.config.max_upload_bytes == 12345
