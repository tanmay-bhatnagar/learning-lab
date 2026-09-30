import importlib.util
import os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_workspace.py"
SPEC = importlib.util.spec_from_file_location("verify_workspace", SCRIPT)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def test_isolated_environment_overrides_personal_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("LEARNING_LAB_ROOT", "/personal/topics")
    monkeypatch.setenv("LEARNING_LAB_STATE_ROOT", "/personal/state")
    monkeypatch.setenv("LEARNING_LAB_SETTINGS", "/personal/settings.json")

    env = verify.isolated_environment(
        os.environ, tmp_path / "run", "http://127.0.0.1:8123"
    )

    assert Path(env["LEARNING_LAB_ROOT"]).is_relative_to(tmp_path)
    assert Path(env["LEARNING_LAB_STATE_ROOT"]).is_relative_to(tmp_path)
    assert Path(env["LEARNING_LAB_SETTINGS"]).is_relative_to(tmp_path)
    assert env["LEARNING_LAB_API_URL"] == "http://127.0.0.1:8123"


def test_isolated_environment_drops_host_telemetry_settings(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "https://telemetry.example.invalid"
    )
    monkeypatch.setenv("OTEL_SERVICE_NAME", "host-service")
    monkeypatch.setenv("FASTAPI_INSTRUMENTATION_ENABLED", "true")
    monkeypatch.setenv(
        "FASTAPI_TELEMETRY_ENDPOINT", "https://telemetry.example.invalid"
    )

    env = verify.isolated_environment(
        os.environ, tmp_path / "run", "http://127.0.0.1:8123"
    )

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

    verify.stop_processes(owned)

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
