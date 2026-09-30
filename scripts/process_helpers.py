"""Shared subprocess helpers for dev and verification scripts."""

from __future__ import annotations

import socket
import subprocess
import time
import urllib.request


def available_port(preferred: int | None = None) -> int:
    """Return `preferred` when free, otherwise an ephemeral loopback port."""
    with socket.socket() as sock:
        if preferred is not None:
            try:
                sock.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(url: str, processes: list[subprocess.Popen], timeout: float = 20) -> None:
    """Wait for an HTTP 200 while detecting early child exits."""
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        exited = [(proc.args, proc.returncode) for proc in processes if proc.poll() is not None]
        if exited:
            raise RuntimeError(f"A service exited during startup: {exited}")
        try:
            with opener.open(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"Startup timed out waiting for {url}")


def stop_processes(processes: list[subprocess.Popen]) -> None:
    """Terminate and reap only the supplied process objects."""
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
