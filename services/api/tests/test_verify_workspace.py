import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


process_helpers = _load_module("process_helpers")
sys.modules["process_helpers"] = process_helpers
verify = _load_module("verify_workspace")


def test_scripts_run_by_path():
    for script in ("dev.py", "verify_workspace.py"):
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr


def test_isolated_environment_overrides_personal_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("LEARNING_LAB_ROOT", "/personal/topics")
    monkeypatch.setenv("LEARNING_LAB_STATE_ROOT", "/personal/state")
    monkeypatch.setenv("LEARNING_LAB_SETTINGS", "/personal/settings.json")

    env = verify.isolated_environment(os.environ, tmp_path / "run", "http://127.0.0.1:8123")

    assert Path(env["LEARNING_LAB_ROOT"]).is_relative_to(tmp_path)
    assert Path(env["LEARNING_LAB_STATE_ROOT"]).is_relative_to(tmp_path)
    assert Path(env["LEARNING_LAB_SETTINGS"]).is_relative_to(tmp_path)
    assert env["LEARNING_LAB_API_URL"] == "http://127.0.0.1:8123"


def test_isolated_environment_drops_host_telemetry_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://telemetry.example.invalid")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "host-service")
    monkeypatch.setenv("FASTAPI_INSTRUMENTATION_ENABLED", "true")
    monkeypatch.setenv("FASTAPI_TELEMETRY_ENDPOINT", "https://telemetry.example.invalid")

    env = verify.isolated_environment(os.environ, tmp_path / "run", "http://127.0.0.1:8123")

    assert not any(key.startswith("OTEL_") for key in env if key != "OTEL_SDK_DISABLED")
    assert not any(key.startswith("FASTAPI_") for key in env)
    assert env["OTEL_SDK_DISABLED"].lower() == "true"


def test_shutdown_only_touches_owned_processes():
    class Process:
        def __init__(self, running):
            self.running = running
            self.terminated = False
            self.waited = False

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.terminated = True
            self.running = False

        def wait(self, timeout=None):
            self.waited = True
            return 0

    owned = [Process(True), Process(False)]
    unrelated = Process(True)

    process_helpers.stop_processes(owned)

    assert owned[0].terminated and owned[0].waited
    assert not owned[1].terminated and owned[1].waited
    assert not unrelated.terminated and not unrelated.waited


def test_pdf_fixture_has_searchable_calibration_text():
    pdf = verify.pdf_fixture()
    assert pdf.startswith(b"%PDF-1.4")
    assert b"Calibration value is 42" in pdf
    assert pdf.endswith(b"%%EOF\n")


def test_require_raises_actionable_runtime_error():
    try:
        verify.require(False, "expected verification failure")
    except RuntimeError as exc:
        assert str(exc) == "expected verification failure"
    else:
        raise AssertionError("require() accepted a failed check")
