import importlib.util
from pathlib import Path
import socket

spec = importlib.util.spec_from_file_location("lab_launcher", Path(__file__).resolve().parents[1] / "scripts/dev.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_occupied_port_uses_another_port_without_closing_existing_listener():
    with socket.socket() as existing:
        existing.bind(("127.0.0.1", 0))
        existing.listen()
        port = existing.getsockname()[1]
        alternate = launcher.available_port(port)
        assert alternate != port
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            connection, _ = existing.accept()
            connection.close()
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", alternate))
