"""Configuration and import side-effect tests."""

import importlib
import sys

MODULES_WITHOUT_IMPORT_SIDE_EFFECTS = (
    "lab.asgi",
    "lab.web.app",
    "lab.chat_prompt",
    "lab.config",
    "lab.models",
    "lab.storage",
    "lab.retrieval",
)


def test_imports_do_not_create_app_or_read_environment(monkeypatch):
    monkeypatch.delenv("LEARNING_LAB_ROOT", raising=False)
    monkeypatch.delenv("LEARNING_LAB_PROFILE_ROOT", raising=False)
    monkeypatch.delenv("LEARNING_LAB_STATE_ROOT", raising=False)
    monkeypatch.delenv("LEARNING_LAB_SETTINGS", raising=False)
    monkeypatch.delenv("LEARNING_LAB_MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)
    monkeypatch.delenv("EMBEDDING_TOKENIZER_ROOT", raising=False)

    for name in MODULES_WITHOUT_IMPORT_SIDE_EFFECTS:
        sys.modules.pop(name, None)
        module = importlib.import_module(name)
        assert not hasattr(module, "app") or module.__dict__.get("app") is None
        if name == "lab.asgi":
            assert callable(module.create_app_factory)
        if name == "lab.web.app":
            assert callable(module.create_app)


def test_create_app_explicit_args_override_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LEARNING_LAB_ROOT", "/should/not/be/used")
    from lab.web.app import create_app

    root = tmp_path / "Learning"
    settings = tmp_path / "settings.json"
    app = create_app(root, settings, max_upload_bytes=12345)
    assert app.state.deps.store.root == root.resolve()
    assert app.state.deps.config.max_upload_bytes == 12345


def test_profile_root_defaults_outside_topic_learning_root(monkeypatch):
    monkeypatch.delenv("LEARNING_LAB_ROOT", raising=False)
    monkeypatch.delenv("LEARNING_LAB_PROFILE_ROOT", raising=False)
    from lab.config import CODE_ROOT, load_config

    config = load_config()

    assert config.profile_root == CODE_ROOT.parent / "Profile"


def test_profile_root_accepts_explicit_and_environment_values(monkeypatch, tmp_path):
    from lab.config import load_config

    explicit = tmp_path / "explicit-profile"
    environmental = tmp_path / "environment-profile"
    monkeypatch.setenv("LEARNING_LAB_PROFILE_ROOT", str(environmental))

    assert load_config().profile_root == environmental.resolve()
    assert load_config(profile_root=explicit).profile_root == explicit.resolve()


def test_create_app_injects_profile_root(tmp_path):
    from lab.config import load_config
    from lab.web.app import create_app

    profile_root = tmp_path / "Profile"
    config = load_config(learning_root=tmp_path / "Learning", profile_root=profile_root)

    app = create_app(config=config)

    assert app.state.deps.config.profile_root == profile_root.resolve()
