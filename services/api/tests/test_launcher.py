import importlib.util
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("process_helpers", ROOT / "scripts/process_helpers.py")
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def test_occupied_port_uses_another_port_without_closing_existing_listener():
    with socket.socket() as existing:
        existing.bind(("127.0.0.1", 0))
        existing.listen()
        port = existing.getsockname()[1]
        alternate = helpers.available_port(port)
        assert alternate != port
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            connection, _ = existing.accept()
            connection.close()
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", alternate))
