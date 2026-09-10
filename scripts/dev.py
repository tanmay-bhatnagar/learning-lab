#!/usr/bin/env python3
"""Run both local services; stop only child processes started by this launcher."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
children = []

def cleanup():
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()


def stop(*_):
    raise KeyboardInterrupt

if not (ROOT / '.venv/bin/python').exists() or not (ROOT / 'apps/web/node_modules').exists():
    sys.exit('Run make setup first.')
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, stop)
try:
    children.append(subprocess.Popen([str(ROOT / '.venv/bin/python'), '-m', 'uvicorn', 'lab.main:app', '--app-dir', 'services/api', '--host', '127.0.0.1', '--port', '8765'], cwd=ROOT))
    children.append(subprocess.Popen(['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], cwd=ROOT / 'apps/web'))
    print('Learning Lab: http://127.0.0.1:5173 (Ctrl-C stops both services)', flush=True)
    while all(child.poll() is None for child in children):
        time.sleep(.5)
    raise SystemExit(next((child.returncode for child in children if child.poll() is not None), 1) or 1)
except KeyboardInterrupt:
    pass
finally:
    cleanup()
