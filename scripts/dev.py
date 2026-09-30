#!/usr/bin/env python3
"""Run local services, selecting an available API port without stopping other apps."""

from pathlib import Path
import os
import signal
import subprocess
import sys
import time

from scripts.process_helpers import available_port, stop_processes, wait_ready

ROOT = Path(__file__).resolve().parents[1]


def stop(*_):
    raise KeyboardInterrupt


def main():
    if not (ROOT / ".venv/bin/python").exists() or not (ROOT / "apps/web/node_modules").exists():
        sys.exit("Run make setup first.")
    if available_port(5173) != 5173:
        sys.exit(
            "Port 5173 is already in use. If Learning Lab is already running, open http://127.0.0.1:5173; otherwise free that port and retry."
        )
    api_port = available_port(8765)
    api_url = f"http://127.0.0.1:{api_port}"
    if api_port != 8765:
        print(f"Port 8765 is occupied; using {api_url} for the Learning Lab API.", flush=True)
    children = []
    runtime_env = {
        **os.environ,
        # Keep Docling artifacts with the project's other local model weights.
        # An explicit path also prevents unexpected background network downloads.
        "DOCLING_ARTIFACTS_PATH": str(ROOT / "data/external/modelweights/docling"),
    }
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    try:
        children.append(
            subprocess.Popen(
                [
                    str(ROOT / ".venv/bin/python"),
                    "-m",
                    "uvicorn",
                    "lab.asgi:app",
                    "--app-dir",
                    "services/api",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                ],
                cwd=ROOT,
                env=runtime_env,
            )
        )
        wait_ready(f"{api_url}/api/health", children)
        env = {**runtime_env, "LEARNING_LAB_API_URL": api_url}
        children.append(
            subprocess.Popen(
                ["npm", "run", "dev", "--", "--port", "5173", "--strictPort"], cwd=ROOT / "apps/web", env=env
            )
        )
        wait_ready("http://127.0.0.1:5173/api/health", children)
        print("Learning Lab is ready: http://127.0.0.1:5173 (Ctrl-C stops both services)", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        return next((child.returncode for child in children if child.poll() is not None), 1) or 1
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        stop_processes(children)


if __name__ == "__main__":
    sys.exit(main())
