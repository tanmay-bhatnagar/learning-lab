"""Document-map section summary workflows (admission graph; execution in gate 12)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from lab.document_map_store import get_document_map
from lab.document_map_summary_store import recover_interrupted_attempts
from lab.errors import Conflict
from lab.runtime_policy import load_runtime_policy
from lab.section_summary import SummaryPlan, build_section_summary_plan
from lab.storage import Store
from lab.web.deps import ActiveSummary
from lab.workflows.runtime import invoke_graph

SUMMARY_ADMISSION_NODE_NAMES: tuple[str, ...] = (
    "recover_attempts",
    "resolve_map",
    "load_policy",
    "plan_fit",
    "write_generating_attempt",
)
SUMMARY_ADMISSION_RECURSION_LIMIT = len(SUMMARY_ADMISSION_NODE_NAMES) + 2

WriteAttemptFn = Callable[..., dict[str, object]]


class SummaryAdmissionState(TypedDict, total=False):
    """Routing state for summary admission (heavy values live in context artifacts)."""


@dataclass
class SummaryAdmissionArtifacts:
    map_record: dict[str, object] | None = None
    runtime_policy: str | None = None
    plan: SummaryPlan | None = None
    attempt_id: str | None = None
    started_at: str | None = None
    attempt: dict[str, object] | None = None


def _new_attempt_id() -> str:
    return uuid4().hex


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class SummaryAdmissionContext:
    """Per-request capabilities and inputs for summary admission."""

    store: Store
    runtime_policy_path: Path
    active_document_map_summaries: dict[str, ActiveSummary]
    write_attempt: WriteAttemptFn
    topic: str
    file_id: str
    section_id: str
    expected_revision: str
    model: str
    context_limit: int
    think: bool | str | None
    artifacts: SummaryAdmissionArtifacts = field(default_factory=SummaryAdmissionArtifacts)
    new_id: Callable[[], str] = field(default=_new_attempt_id)
    now_iso: Callable[[], str] = field(default=_now_iso)


@dataclass(frozen=True, slots=True)
class SummaryAdmissionResult:
    attempt_id: str
    attempt: dict[str, object]
    plan: SummaryPlan


async def recover_attempts(
    _state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]
) -> SummaryAdmissionState:
    ctx = runtime.context
    active_ids = {
        attempt_id
        for attempt_id, active in ctx.active_document_map_summaries.items()
        if active.topic == ctx.topic and active.file_id == ctx.file_id
    }
    recover_interrupted_attempts(
        ctx.store,
        ctx.topic,
        ctx.file_id,
        active_attempt_ids=active_ids,
        finished_at=ctx.now_iso(),
    )
    return {}


async def resolve_map(
    _state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]
) -> SummaryAdmissionState:
    ctx = runtime.context
    current = get_document_map(ctx.store, ctx.topic, ctx.file_id)
    if current["status"] != "ready" or current["map"] is None:
        raise Conflict("Rebuild the document map before generating a summary.")
    map_record = current["map"]
    if map_record["revision"] != ctx.expected_revision:
        raise Conflict("The selected document map revision changed. Reload it before generating a summary.")
    ctx.artifacts.map_record = map_record
    return {}


async def load_policy(
    _state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]
) -> SummaryAdmissionState:
    ctx = runtime.context
    ctx.artifacts.runtime_policy = load_runtime_policy(ctx.runtime_policy_path)
    return {}


async def plan_fit(_state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]) -> SummaryAdmissionState:
    ctx = runtime.context
    art = ctx.artifacts
    if art.map_record is None or art.runtime_policy is None:
        msg = "summary admission plan_fit requires map and policy artifacts"
        raise RuntimeError(msg)
    art.attempt_id = ctx.new_id()
    art.started_at = ctx.now_iso()
    art.plan = build_section_summary_plan(
        art.map_record,
        ctx.section_id,
        runtime_policy=art.runtime_policy,
        model=ctx.model,
        context_limit=ctx.context_limit,
        think=ctx.think,
        attempt_id=art.attempt_id,
        started_at=art.started_at,
    )
    return {}


async def write_generating_attempt(
    _state: SummaryAdmissionState, runtime: Runtime[SummaryAdmissionContext]
) -> SummaryAdmissionState:
    ctx = runtime.context
    art = ctx.artifacts
    if art.plan is None or art.attempt_id is None:
        msg = "summary admission write requires a planned generating attempt"
        raise RuntimeError(msg)
    attempt = art.plan["attempt"]
    ctx.write_attempt(ctx.store, ctx.topic, ctx.file_id, attempt)
    art.attempt = attempt
    ctx.active_document_map_summaries[art.attempt_id] = ActiveSummary(
        topic=ctx.topic,
        file_id=ctx.file_id,
        revision=ctx.expected_revision,
        section_id=ctx.section_id,
    )
    return {}


def compile_summary_admission_graph() -> CompiledStateGraph[SummaryAdmissionState, SummaryAdmissionContext, Any, Any]:
    """Build the summary admission graph (compile once per app)."""
    graph: StateGraph[SummaryAdmissionState, SummaryAdmissionContext] = StateGraph(
        SummaryAdmissionState, context_schema=SummaryAdmissionContext
    )
    graph.add_node("recover_attempts", recover_attempts)
    graph.add_node("resolve_map", resolve_map)
    graph.add_node("load_policy", load_policy)
    graph.add_node("plan_fit", plan_fit)
    graph.add_node("write_generating_attempt", write_generating_attempt)
    graph.add_edge(START, "recover_attempts")
    graph.add_edge("recover_attempts", "resolve_map")
    graph.add_edge("resolve_map", "load_policy")
    graph.add_edge("load_policy", "plan_fit")
    graph.add_edge("plan_fit", "write_generating_attempt")
    graph.add_edge("write_generating_attempt", END)
    return graph.compile()


def summary_admission_mermaid(compiled: CompiledStateGraph[Any, Any, Any, Any]) -> str:
    """Return local Mermaid text for the compiled admission topology."""
    return compiled.get_graph().draw_mermaid()


async def run_summary_admission(
    graph: CompiledStateGraph[Any, Any, Any, Any],
    context: SummaryAdmissionContext,
) -> SummaryAdmissionResult:
    """Await summary admission; domain errors propagate with original types."""
    await invoke_graph(
        graph,
        {},
        context=context,
        recursion_limit=SUMMARY_ADMISSION_RECURSION_LIMIT,
    )
    art = context.artifacts
    if art.plan is None or art.attempt is None or art.attempt_id is None:
        msg = "summary admission finished without attempt artifacts"
        raise RuntimeError(msg)
    return SummaryAdmissionResult(attempt_id=art.attempt_id, attempt=art.attempt, plan=art.plan)
