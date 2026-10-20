"""Test-only helpers for inspecting compiled LangGraph graphs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

GraphEdge = tuple[str, str, object | None, bool]


def draw_mermaid(compiled: Any) -> str:
    """Return local Mermaid text for a compiled graph (never draw_mermaid_png)."""
    return compiled.get_graph().draw_mermaid()


def graph_edge_set(compiled: Any) -> frozenset[GraphEdge]:
    """Return (source, target, edge data, conditional) tuples from the compiled topology."""
    return frozenset((edge.source, edge.target, edge.data, edge.conditional) for edge in compiled.get_graph().edges)


def graph_callables(compiled: Any) -> list[tuple[str, Callable[..., Any]]]:
    """Return named node and branch callables from a compiled LangGraph graph."""
    found: list[tuple[str, Callable[..., Any]]] = []
    for name, spec in compiled.builder.nodes.items():
        runnable = spec.runnable
        fn = getattr(runnable, "afunc", None) or getattr(runnable, "func", None)
        if fn is not None:
            found.append((f"node:{name}", fn))
    for branches in compiled.builder.branches.values():
        for branch in branches.values():
            path = branch.path
            fn = getattr(path, "afunc", None) or getattr(path, "func", None)
            if fn is not None:
                found.append((f"branch:{getattr(fn, '__name__', 'router')}", fn))
    return found
