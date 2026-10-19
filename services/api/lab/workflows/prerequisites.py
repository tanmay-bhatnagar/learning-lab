"""LangGraph admission for personalized prerequisite generation."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from lab.document_map_store import get_document_map
from lab.errors import Conflict
from lab.prerequisite_store import (
    get_prerequisite_state,
    recover_interrupted_attempts,
    write_prerequisite_attempt,
)
from lab.prerequisites import build_prerequisite_plan
from lab.profile_store import ProfileStore
from lab.runtime_policy import load_runtime_policy
from lab.storage import Store
from lab.workflows.runtime import invoke_graph

PREREQUISITE_ADMISSION_RECURSION_LIMIT = 8

PREREQUISITE_ADMISSION_MERMAID = """
flowchart TD
    START --> recover_and_reconcile
    recover_and_reconcile --> resolve_map
    resolve_map --> select_cv
    select_cv --> load_policy
    load_policy --> plan_fit
    plan_fit --> write_generating_attempt
    write_generating_attempt --> END
""".strip()


class PrerequisiteAdmissionState(TypedDict, total=False):
    topic_id: str
    file_id: str
    section_id: str
    revision: str
    model: str
    context_limit: int
    think: bool | str | None
    goal: str | None
    attempt_id: str
    assessment_id: str


@dataclass
class PrerequisiteAdmissionArtifacts:
    map_record: dict[str, object] | None = None
    selected_cv: dict[str, object] | None = None
    cv_text: str | None = None
    runtime_policy: str | None = None
    plan: dict[str, Any] | None = None
    attempt: dict[str, object] | None = None
    attempt_id: str | None = None
    assessment_id: str | None = None
    started_at: str | None = None


@dataclass(frozen=True, slots=True)
class PrerequisiteAdmissionCapabilities:
    store: Store
    profile_store: ProfileStore
    runtime_policy_path: Path
    now: Callable[[], str]
    new_attempt_ids: Callable[[], tuple[str, str]]
    register_active: Callable[[str], None]


@dataclass
class PrerequisiteAdmissionContext:
    capabilities: PrerequisiteAdmissionCapabilities
    artifacts: PrerequisiteAdmissionArtifacts = field(default_factory=PrerequisiteAdmissionArtifacts)
    topic_id: str = ""
    file_id: str = ""
    section_id: str = ""
    revision: str = ""
    model: str = ""
    context_limit: int = 0
    think: bool | str | None = None
    goal: str | None = None
    active_attempt_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class PrerequisiteAdmitted:
    attempt_id: str
    assessment_id: str
    attempt: dict[str, object]
    plan: dict[str, Any]
    selected_cv: dict[str, object]
    cv_text: str


async def recover_and_reconcile(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    recover_file_state(
        ctx.capabilities.store,
        ctx.capabilities.profile_store,
        ctx.topic_id,
        ctx.file_id,
        ctx.active_attempt_ids,
        now=ctx.capabilities.now,
    )
    return {}


async def resolve_map(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    current = get_document_map(ctx.capabilities.store, ctx.topic_id, ctx.file_id)
    if current["status"] != "ready" or current["map"] is None:
        raise Conflict("Build the current document map before generating prerequisites.")
    map_record = current["map"]
    if map_record["revision"] != ctx.revision:
        raise Conflict("The selected document map revision changed. Reload it before generating prerequisites.")
    ctx.artifacts.map_record = map_record
    return {}


async def select_cv(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    profile = ctx.capabilities.profile_store.read_profile()
    selected = next((item for item in profile["cvs"] if item["id"] == profile["active_cv_id"]), None)
    if selected is None or selected["status"] != "ready" or selected["revoked"]:
        raise Conflict("Select a successfully extracted, non-revoked CV before generating prerequisites.")
    cv_text = ctx.capabilities.profile_store.read_extracted_text(selected["id"])
    if hashlib.sha256(cv_text.encode("utf-8")).hexdigest() != selected["extracted_sha256"]:
        raise Conflict("The selected CV text changed. Reload the CV and retry.")
    ctx.artifacts.selected_cv = selected
    ctx.artifacts.cv_text = cv_text
    return {}


async def load_policy(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    ctx.artifacts.runtime_policy = load_runtime_policy(ctx.capabilities.runtime_policy_path)
    return {}


async def plan_fit(
    _state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    map_record = ctx.artifacts.map_record
    selected = ctx.artifacts.selected_cv
    cv_text = ctx.artifacts.cv_text
    runtime_policy = ctx.artifacts.runtime_policy
    if map_record is None or selected is None or cv_text is None or runtime_policy is None:
        msg = "Admission artifacts are incomplete before planning."
        raise RuntimeError(msg)
    attempt_id, assessment_id = ctx.capabilities.new_attempt_ids()
    started_at = ctx.capabilities.now()
    plan = build_prerequisite_plan(
        map_record,
        ctx.section_id,
        selected_cv=selected,
        cv_text=cv_text,
        runtime_policy=runtime_policy,
        goal=ctx.goal,
        model=ctx.model,
        context_limit=ctx.context_limit,
        think=ctx.think,
        assessment_id=assessment_id,
        attempt_id=attempt_id,
        started_at=started_at,
    )
    ctx.artifacts.plan = plan
    ctx.artifacts.attempt_id = attempt_id
    ctx.artifacts.assessment_id = assessment_id
    ctx.artifacts.started_at = started_at
    return {"attempt_id": attempt_id, "assessment_id": assessment_id}


async def write_generating_attempt(
    state: PrerequisiteAdmissionState,
    runtime: Runtime[PrerequisiteAdmissionContext],
) -> PrerequisiteAdmissionState:
    ctx = runtime.context
    plan = ctx.artifacts.plan
    attempt_id = ctx.artifacts.attempt_id
    assessment_id = ctx.artifacts.assessment_id
    started_at = ctx.artifacts.started_at
    if plan is None or attempt_id is None or assessment_id is None or started_at is None:
        msg = "Admission artifacts are incomplete before persisting the generating attempt."
        raise RuntimeError(msg)
    provenance = plan["provenance"]
    attempt: dict[str, object] = {
        "id": attempt_id,
        "assessment_id": assessment_id,
        "topic_id": ctx.topic_id,
        "file_id": ctx.file_id,
        "map_revision": ctx.revision,
        "section_id": ctx.section_id,
        "status": "generating",
        "started_at": started_at,
        "finished_at": None,
        "provenance": {
            "prompt_version": provenance["prompt_version"],
            "source_sha256": provenance["source_sha256"],
            "runtime_policy_sha256": provenance["runtime_policy_sha256"],
            "cv_id": provenance["cv_id"],
            "cv_text_sha256": provenance["cv_text_sha256"],
            "goal": provenance["goal"],
            "model": ctx.model,
        },
        "diagnostic": None,
    }
    write_prerequisite_attempt(ctx.capabilities.store, ctx.topic_id, ctx.file_id, attempt)
    ctx.capabilities.register_active(attempt_id)
    ctx.artifacts.attempt = attempt
    return {"attempt_id": attempt_id, "assessment_id": assessment_id}


ADMISSION_NODE_CALLABLES: tuple[Any, ...] = (
    recover_and_reconcile,
    resolve_map,
    select_cv,
    load_policy,
    plan_fit,
    write_generating_attempt,
)


def compile_prerequisite_admission_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    """Build the prerequisite admission graph (compile once per app router)."""
    graph = StateGraph(PrerequisiteAdmissionState, context_schema=PrerequisiteAdmissionContext)
    graph.add_node("recover_and_reconcile", recover_and_reconcile)
    graph.add_node("resolve_map", resolve_map)
    graph.add_node("select_cv", select_cv)
    graph.add_node("load_policy", load_policy)
    graph.add_node("plan_fit", plan_fit)
    graph.add_node("write_generating_attempt", write_generating_attempt)
    graph.add_edge(START, "recover_and_reconcile")
    graph.add_edge("recover_and_reconcile", "resolve_map")
    graph.add_edge("resolve_map", "select_cv")
    graph.add_edge("select_cv", "load_policy")
    graph.add_edge("load_policy", "plan_fit")
    graph.add_edge("plan_fit", "write_generating_attempt")
    graph.add_edge("write_generating_attempt", END)
    return graph.compile()


async def admit_prerequisite_generation(
    graph: CompiledStateGraph[Any, Any, Any, Any],
    *,
    capabilities: PrerequisiteAdmissionCapabilities,
    topic_id: str,
    file_id: str,
    section_id: str,
    revision: str,
    model: str,
    context_limit: int,
    think: bool | str | None,
    goal: str | None,
    active_attempt_ids: set[str],
) -> PrerequisiteAdmitted:
    """Run admission preflight and persist the single generating attempt."""
    context = PrerequisiteAdmissionContext(
        capabilities=capabilities,
        topic_id=topic_id,
        file_id=file_id,
        section_id=section_id,
        revision=revision,
        model=model,
        context_limit=context_limit,
        think=think,
        goal=goal,
        active_attempt_ids=active_attempt_ids,
    )
    initial: PrerequisiteAdmissionState = {
        "topic_id": topic_id,
        "file_id": file_id,
        "section_id": section_id,
        "revision": revision,
        "model": model,
        "context_limit": context_limit,
        "think": think,
        "goal": goal,
    }
    await invoke_graph(
        graph,
        initial,
        context=context,
        recursion_limit=PREREQUISITE_ADMISSION_RECURSION_LIMIT,
    )
    artifacts = context.artifacts
    if (
        artifacts.attempt is None
        or artifacts.plan is None
        or artifacts.selected_cv is None
        or artifacts.cv_text is None
        or artifacts.attempt_id is None
        or artifacts.assessment_id is None
    ):
        msg = "Prerequisite admission completed without required artifacts."
        raise RuntimeError(msg)
    return PrerequisiteAdmitted(
        attempt_id=artifacts.attempt_id,
        assessment_id=artifacts.assessment_id,
        attempt=artifacts.attempt,
        plan=artifacts.plan,
        selected_cv=artifacts.selected_cv,
        cv_text=artifacts.cv_text,
    )


def recover_file_state(
    store: Store,
    profile_store: ProfileStore,
    topic: str,
    file_id: str,
    active_ids: set[str],
    *,
    now: Callable[[], str],
) -> None:
    """Recover interrupted attempts and discard unpublished rows for terminal failures."""
    recover_interrupted_attempts(store, topic, file_id, active_attempt_ids=active_ids, finished_at=now())
    state = get_prerequisite_state(store, topic, file_id)
    for attempt in state["attempts"]:
        if attempt["status"] in {"error", "cancelled", "interrupted"}:
            discard_if_unpublished(profile_store, store, topic, file_id, attempt["id"], attempt["assessment_id"])


def discard_if_unpublished(
    profile_store: ProfileStore,
    store: Store,
    topic: str,
    file_id: str,
    attempt_id: str,
    assessment_id: str,
) -> None:
    """Remove unpublished model requirements when a terminal attempt did not publish."""
    state = get_prerequisite_state(store, topic, file_id)
    attempt = next((item for item in state["attempts"] if item["id"] == attempt_id), None)
    if attempt is None or attempt["status"] not in {"error", "cancelled", "interrupted"}:
        return
    if assessment_id_is_published(state, assessment_id):
        return
    profile_store.discard_unpublished_pending(topic_id=topic, assessment_id=assessment_id)


def published_assessment(
    state: Mapping[str, object],
    attempt_id: str,
    assessment_id: str,
) -> dict[str, object] | None:
    """Return a published assessment when it matches both attempt and assessment IDs."""
    assessments = state["assessments"]
    if not isinstance(assessments, list):
        return None
    return next(
        (
            item
            for item in assessments
            if isinstance(item, dict)
            and item.get("attempt_id") == attempt_id
            and item.get("assessment_id") == assessment_id
        ),
        None,
    )


def assessment_id_is_published(state: Mapping[str, object], assessment_id: str) -> bool:
    assessments = state["assessments"]
    if not isinstance(assessments, list):
        return False
    return any(isinstance(item, dict) and item.get("assessment_id") == assessment_id for item in assessments)


def admission_callables_are_coroutines() -> bool:
    """Return whether every admission node callable is an async function."""
    return all(inspect.iscoroutinefunction(callable_) for callable_ in ADMISSION_NODE_CALLABLES)
