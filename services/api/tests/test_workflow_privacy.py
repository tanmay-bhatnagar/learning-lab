"""Tracing suppression and graph invocation architecture guards."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parent.parent
LAB_ROOT = API_ROOT / "lab"
RUNTIME_PATH = LAB_ROOT / "workflows" / "runtime.py"

_GRAPH_INVOCATION_ATTRS = frozenset({"ainvoke", "astream", "astream_events", "invoke", "stream"})


def _receiver_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _full_receiver(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - best-effort AST helper
        return ""


def test_lab_graph_invocations_only_in_runtime_module() -> None:
    violations: list[str] = []
    for path in sorted(LAB_ROOT.rglob("*.py")):
        if path.resolve() == RUNTIME_PATH.resolve():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in _GRAPH_INVOCATION_ATTRS:
                continue
            receiver = _full_receiver(func.value).lower()
            if "graph" not in receiver:
                continue
            violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {func.attr}")
    assert violations == []


def test_workflows_do_not_import_lab_web() -> None:
    workflows_root = LAB_ROOT / "workflows"
    violations: list[str] = []
    for path in sorted(workflows_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "lab.web" or alias.name.startswith("lab.web."):
                        violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "lab.web" or node.module.startswith("lab.web."):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} from {node.module}")
    assert violations == []


def test_lab_has_no_draw_mermaid_png() -> None:
    hits = [
        str(path.relative_to(REPO_ROOT))
        for path in LAB_ROOT.rglob("*.py")
        if "draw_mermaid_png" in path.read_text(encoding="utf-8")
    ]
    assert hits == []


_PRIVACY_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import os
    import socket
    import sys

    os.environ.update(
        {
            "LANGSMITH_TRACING": "true",
            "LANGCHAIN_TRACING_V2": "true",
            "LANGSMITH_API_KEY": "lsv2_fake_test_key",
            "LANGCHAIN_API_KEY": "lsv2_fake_test_key",
            "LANGSMITH_ENDPOINT": "http://203.0.113.10:9",
        }
    )

    attempts = []
    real_connect = socket.socket.connect

    def spy(self, address):
        attempts.append(address)
        raise OSError("blocked")

    socket.socket.connect = spy

    from langgraph.graph import END, START, StateGraph
    from typing import TypedDict

    class S(TypedDict, total=False):
        out: str

    async def node(state: S) -> S:
        return {"out": "ok"}

    graph_builder = StateGraph(S)
    graph_builder.add_node("n", node)
    graph_builder.add_edge(START, "n")
    graph_builder.add_edge("n", END)
    graph = graph_builder.compile()

    async def main(mode: str) -> None:
        if mode == "invoke_graph":
            from lab.workflows.runtime import invoke_graph

            await invoke_graph(graph, {}, context=None, recursion_limit=5)
        else:
            await graph.ainvoke({})
        await asyncio.sleep(1.5)
        print(len(attempts))

    asyncio.run(main(sys.argv[1]))
    """
)


@pytest.mark.parametrize(
    ("mode", "expect_attempts"),
    [("invoke_graph", 0), ("direct", None)],
)
def test_tracing_suppression_subprocess(mode: str, expect_attempts: int | None) -> None:
    env = {**os.environ, "PYTHONPATH": str(API_ROOT)}
    completed = subprocess.run(
        [sys.executable, "-c", _PRIVACY_SCRIPT, mode],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    count = int(completed.stdout.strip().splitlines()[-1])
    if expect_attempts is not None:
        assert count == expect_attempts
    else:
        assert count > 0
