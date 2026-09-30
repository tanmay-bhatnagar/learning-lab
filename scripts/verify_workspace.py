#!/usr/bin/env python3
"""Run a bounded, isolated backend and browser-proxy verification."""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from pathlib import Path

from scripts.process_helpers import available_port, stop_processes, wait_ready

ROOT = Path(__file__).resolve().parents[1]


def isolated_environment(inherited_env: Mapping[str, str], run_dir: Path, api_url: str) -> dict[str, str]:
    """Build service settings whose persisted data cannot use inherited paths."""
    run_dir = Path(run_dir).resolve()
    data_root = run_dir / "Learning"
    state_root = run_dir / "state"
    env = dict(inherited_env)
    for key in tuple(env):
        if key.startswith("OTEL_") or key.startswith("FASTAPI_"):
            env.pop(key)
    return {
        **env,
        "LEARNING_LAB_ROOT": str(data_root),
        "LEARNING_LAB_STATE_ROOT": str(state_root),
        "LEARNING_LAB_SETTINGS": str(state_root / "settings.json"),
        "LEARNING_LAB_API_URL": api_url,
        "DOCLING_ARTIFACTS_PATH": str(run_dir / "docling-artifacts"),
        "OTEL_SDK_DISABLED": "true",
    }


def preflight() -> tuple[str, str, str]:
    """Check required local interpreters, installed packages, and entrypoints."""
    vite = ROOT / "apps/web/node_modules/vite/bin/vite.js"
    node = shutil.which("node")
    problems = []
    python = sys.executable
    if not node:
        problems.append("Node.js executable not found on PATH; install Node.js and retry.")
    if not vite.is_file():
        problems.append(f"Vite entrypoint missing: {vite}. Run `npm ci` in apps/web.")
    check = subprocess.run(
        [python, "-c", "import fastapi, multipart, markitdown, uvicorn"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if check.returncode:
        problems.append(
            f"Backend dependencies are unavailable to {python}; install the Code API requirements in this environment. "
            + check.stderr.strip()
        )
    if problems:
        raise RuntimeError("\n".join(problems))
    return str(python), node, str(vite)


def pdf_fixture() -> bytes:
    """Create a small searchable PDF fixture without external services."""
    text = "Learning Lab verification. Calibration value is 42."
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(('BT /F1 18 Tf 72 720 Td (' + escaped + ') Tj ET').encode())} >>\nstream\nBT /F1 18 Tf 72 720 Td (".encode()
        + escaped.encode()
        + b") Tj ET\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, content in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + content + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def request(url, method="GET", body=None, headers=None, timeout=10):
    """Make a local HTTP request without inheriting proxy environment settings."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with opener.open(req, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def require(condition: bool, message: str) -> None:
    """Raise a useful verification failure independently of Python optimization."""
    if not condition:
        raise RuntimeError(message)


def multipart_upload(url, pdf):
    """Upload a synthetic PDF selecting MarkItDown explicitly."""
    boundary = "----learninglab" + uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="parser"\r\n\r\nmarkitdown\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="calibration.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode(),
        pdf,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return request(
        url,
        "POST",
        b"".join(parts),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def run_verification(run_dir, processes, api_port, web_port):
    """Exercise services and return evidence for this verification run."""
    api_url = f"http://127.0.0.1:{api_port}"
    web_url = f"http://127.0.0.1:{web_port}"
    wait_ready(f"{web_url}/api/health", processes, timeout=35)
    status, _, body = request(f"{web_url}/api/health")
    require(
        status == 200 and json.loads(body).get("status") == "ok",
        f"Health check failed: HTTP {status}: {body!r}",
    )
    status, _, body = request(f"{web_url}/api/topics")
    require(status == 200, f"Initial topic-list request failed: HTTP {status}: {body!r}")
    initial_topics = json.loads(body).get("topics")
    require(
        initial_topics == [],
        f"Isolated topic list was not empty at startup: {initial_topics!r}",
    )
    status, _, body = request(
        f"{web_url}/api/topics",
        "POST",
        b'{"name":"Synthetic verification"}',
        {"Content-Type": "application/json"},
    )
    require(status == 201, f"Topic creation failed: HTTP {status}: {body!r}")
    topic = json.loads(body)
    pdf = pdf_fixture()
    (run_dir / "fixture.pdf").write_bytes(pdf)
    status, _, body = multipart_upload(f"{web_url}/api/topics/{topic['id']}/files", pdf)
    require(status == 201, f"PDF upload failed: HTTP {status}: {body!r}")
    record = json.loads(body)
    require(record.get("status") == "ready", f"PDF conversion did not complete: {record!r}")
    require(record.get("parser") == "markitdown", f"Unexpected parser reported: {record!r}")
    status, _, body = request(f"{web_url}/api/topics/{topic['id']}/files/{record['id']}/markdown")
    markdown = json.loads(body).get("markdown", "")
    require(
        status == 200 and "42" in markdown,
        f"Markdown did not contain calibration value 42 (HTTP {status}): {markdown!r}",
    )
    status, _, original = request(f"{web_url}/api/topics/{topic['id']}/files/{record['id']}/original")
    require(status == 200 and original == pdf, "Original PDF bytes were not preserved.")
    topic_dir = run_dir / "Learning" / topic["id"]
    require(
        (topic_dir / record["original_name"]).read_bytes() == pdf,
        "Original was not persisted under the isolated topic root.",
    )
    require(
        "42" in (topic_dir / record["markdown_name"]).read_text(),
        "Converted Markdown was not persisted under the isolated topic root.",
    )
    return {
        "status": "passed",
        "api_url": api_url,
        "web_url": web_url,
        "topic_id": topic["id"],
        "file_id": record["id"],
        "parser": "markitdown",
        "calibration_value_found": True,
        "original_bytes_preserved": True,
    }


def handle_interrupt(_signum, _frame):
    """Convert terminal interrupts into the normal cleanup path."""
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    """Launch services and run verification, or leave isolated services serving."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Keep isolated services running for browser checks.",
    )
    args = parser.parse_args(argv)
    run_dir = ROOT / ".local/verification" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True)
    evidence_path = run_dir / "evidence.json"
    evidence = {
        "run_dir": str(run_dir.resolve()),
        "mode": "serve" if args.serve else "verify",
        "status": "starting",
    }
    processes = []
    log_streams = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle_interrupt)
    try:
        python, node, vite = preflight()
        fixture = pdf_fixture()
        fixture_path = run_dir / "fixture.pdf"
        fixture_path.write_bytes(fixture)
        api_port = available_port(None)
        if args.serve:
            web_port = 5173
            with socket.socket() as listener:
                try:
                    listener.bind(("127.0.0.1", web_port))
                except OSError as exc:
                    raise RuntimeError(
                        "Port 5173 is occupied. --serve uses this fixed port because the app only allows browser writes from port 5173; close that listener and retry. No process was stopped."
                    ) from exc
        else:
            web_port = available_port(None)
        while web_port == api_port:
            if args.serve:
                api_port = available_port(None)
            else:
                web_port = available_port(None)
        api_url = f"http://127.0.0.1:{api_port}"
        env = isolated_environment(os.environ, run_dir, api_url)
        logs = {}
        for name in ("api", "vite"):
            logs[name] = (run_dir / f"{name}.log").open("w", encoding="utf-8")
            log_streams.append(logs[name])
        processes.append(
            subprocess.Popen(
                [
                    python,
                    "-m",
                    "uvicorn",
                    "lab.asgi:app",
                    "--app-dir",
                    str(ROOT / "services/api"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                ],
                cwd=ROOT,
                env=env,
                stdout=logs["api"],
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        )
        wait_ready(f"{api_url}/api/health", processes, timeout=35)
        processes.append(
            subprocess.Popen(
                [
                    node,
                    vite,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(web_port),
                    "--strictPort",
                ],
                cwd=ROOT / "apps/web",
                env=env,
                stdout=logs["vite"],
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        )
        if args.serve:
            wait_ready(f"http://127.0.0.1:{web_port}/api/health", processes, timeout=35)
            evidence.update(
                status="serving",
                api_url=api_url,
                web_url=f"http://127.0.0.1:{web_port}",
                fixture_path=str(fixture_path.resolve()),
            )
            evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
            print(
                f"Web: {evidence['web_url']}\nAPI: {api_url}\nFixture: {fixture_path}\nEvidence: {evidence_path}\nBrowser-write limitation: the app accepts write requests only from localhost:5173; --serve uses that port.",
                flush=True,
            )
            while all(process.poll() is None for process in processes):
                time.sleep(0.5)
            raise RuntimeError("A verification service stopped unexpectedly; see run logs.")
        evidence.update(run_verification(run_dir, processes, api_port, web_port))
        evidence["fixture_path"] = str(fixture_path.resolve())
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        print(
            f"PASS: proxy health, topic creation, MarkItDown PDF extraction, and original preservation.\nEvidence: {evidence_path}"
        )
        return 0
    except KeyboardInterrupt:
        evidence.update(status="stopped_by_user")
        return 0
    except Exception as exc:  # noqa: BLE001 - records any failure in the evidence file
        evidence.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        print(
            f"Verification failed: {exc}\nSee logs and evidence at {run_dir}",
            file=sys.stderr,
        )
        return 1
    finally:
        stop_processes(processes)
        for stream in log_streams:
            stream.close()
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
