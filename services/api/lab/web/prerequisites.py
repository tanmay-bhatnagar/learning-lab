"""HTTP lifecycle for on-demand, CV-grounded section prerequisite assessments."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from anyio import CancelScope
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from lab.document_map_store import get_document_map
from lab.errors import Conflict, InvalidInput, NotFound
from lab.prerequisite_store import current_assessment, get_prerequisite_state
from lab.web.deps import ActivePrerequisite, AppDeps
from lab.web.locks import acquire_topic_lock, topic_lock_busy
from lab.web.middleware import FinalizedStreamingResponse
from lab.workflows.prerequisite_publication import PrerequisitePublicationOutcome
from lab.workflows.prerequisites import (
    PrerequisiteAdmissionCapabilities,
    PrerequisiteExecutionBundle,
    admit_prerequisite_generation,
    build_prerequisite_graph_run,
    compile_prerequisite_admission_graph,
    compile_prerequisite_execution_graph,
    finalize_prerequisite_run,
    recover_file_state,
)
from lab.workflows.runtime import PublishOnce

logger = logging.getLogger(__name__)


class PrerequisiteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1, max_length=200)
    context_limit: int = Field(default=32768, ge=1024, le=32768)
    think: bool | Literal["low", "medium", "high"] | None = None
    goal: str | None = Field(default=None, max_length=2000)


def router(deps: AppDeps) -> APIRouter:
    admission_graph = compile_prerequisite_admission_graph()
    execution_graph = compile_prerequisite_execution_graph()
    routes = APIRouter()

    @routes.get("/api/topics/{topic}/files/{file_id}/prerequisites")
    async def read_prerequisites(
        topic: str,
        file_id: str,
        section_id: str | None = None,
        assessment_id: str | None = None,
    ):
        if assessment_id is not None:
            if section_id is not None:
                raise InvalidInput("Choose either a historical assessment or a current section selection.")
            state = get_prerequisite_state(deps.store, topic, file_id)
            if not any(item["assessment_id"] == assessment_id for item in state["assessments"]):
                raise NotFound("Completed prerequisite assessment not found.")
            return {
                "schema_version": state["schema_version"],
                "topic_id": topic,
                "file_id": file_id,
                "map_revision": None,
                "selected_cv": None,
                "attempts": state["attempts"],
                "assessments": state["assessments"],
                "current_assessment": None,
            }

        await _recover_if_idle(deps, topic, file_id)
        state = get_prerequisite_state(deps.store, topic, file_id)
        current = get_document_map(deps.store, topic, file_id)
        profile = deps.profile_store.read_profile()
        cv = next((item for item in profile["cvs"] if item["id"] == profile["active_cv_id"]), None)
        selected_cv = None
        if cv is not None and cv["status"] == "ready" and not cv["revoked"]:
            selected_cv = {
                "id": cv["id"],
                "original_name": cv["original_name"],
                "extracted_sha256": cv["extracted_sha256"],
            }
        map_record = current["map"] if current["status"] == "ready" else None
        selected_section = section_id
        if selected_section is None and state["assessments"]:
            selected_section = state["assessments"][-1]["section_id"]
        current_result = None
        if map_record is not None and selected_cv is not None and selected_section is not None:
            current_result = current_assessment(
                state,
                map_revision=str(map_record["revision"]),
                section_id=selected_section,
                cv_id=str(selected_cv["id"]),
                cv_text_sha256=str(selected_cv["extracted_sha256"]),
            )
        return {
            "schema_version": state["schema_version"],
            "topic_id": topic,
            "file_id": file_id,
            "map_revision": map_record["revision"] if map_record is not None else None,
            "selected_cv": selected_cv,
            "attempts": state["attempts"],
            "assessments": state["assessments"],
            "current_assessment": current_result,
        }

    @routes.post("/api/topics/{topic}/files/{file_id}/map/sections/{section_id}/prerequisites")
    async def generate_prerequisites(topic: str, file_id: str, section_id: str, body: PrerequisiteInput):
        lease = await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)
        try:
            active_ids = {
                attempt_id
                for attempt_id, active in deps.active_prerequisite_attempts.items()
                if active.topic == topic and active.file_id == file_id
            }

            def register_active(attempt_id: str) -> None:
                deps.active_prerequisite_attempts[attempt_id] = ActivePrerequisite(
                    topic=topic,
                    file_id=file_id,
                    revision=body.revision,
                    section_id=section_id,
                )

            admitted = await admit_prerequisite_generation(
                admission_graph,
                capabilities=PrerequisiteAdmissionCapabilities(
                    store=deps.store,
                    profile_store=deps.profile_store,
                    runtime_policy_path=deps.config.runtime_policy_path,
                    now=_now,
                    new_attempt_ids=lambda: (uuid.uuid4().hex, uuid.uuid4().hex),
                    register_active=register_active,
                ),
                topic_id=topic,
                file_id=file_id,
                section_id=section_id,
                revision=body.revision,
                model=body.model,
                context_limit=body.context_limit,
                think=body.think,
                goal=body.goal,
                active_attempt_ids=active_ids,
            )
            attempt_id = admitted.attempt_id
            assessment_id = admitted.assessment_id
            attempt = admitted.attempt
            lease.hand_off()
        except BaseException:
            lease.release()
            raise

        publish_once: PublishOnce[PrerequisitePublicationOutcome] = PublishOnce()

        def unregister_active(active_attempt_id: str) -> None:
            deps.active_prerequisite_attempts.pop(active_attempt_id, None)

        execution_bundle = PrerequisiteExecutionBundle(
            store=deps.store,
            profile_store=deps.profile_store,
            model_backend=deps.model_backend,
            generation_lock=deps.model_generation_lock,
            topic_id=topic,
            file_id=file_id,
            section_id=section_id,
            revision=body.revision,
            model=body.model,
            context_limit=body.context_limit,
            think=body.think,
            attempt_id=attempt_id,
            assessment_id=assessment_id,
            attempt=attempt,
            plan=admitted.plan,
            selected_cv=admitted.selected_cv,
            cv_text=admitted.cv_text,
            now=_now,
        )
        handle = build_prerequisite_graph_run(
            graph=execution_graph,
            bundle=execution_bundle,
            publish_once=publish_once,
        )
        deps.active_runs.register(handle.run)
        closed = False

        def line(event: dict[str, object]) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        async def finish() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            with CancelScope(shield=True):
                try:
                    await finalize_prerequisite_run(
                        handle,
                        unregister_active=unregister_active,
                        attempt_id=attempt_id,
                    )
                finally:
                    deps.active_runs.unregister(handle.run)
                    lease.release()

        async def events():
            yield line(
                {
                    "type": "started",
                    "attempt_id": attempt_id,
                    "revision": body.revision,
                    "section_id": section_id,
                    "attempt": attempt,
                }
            )
            try:
                async for event in handle.run.events():
                    yield line(dict(event))
            finally:
                await finish()

        try:
            return FinalizedStreamingResponse(
                events(),
                on_close=finish,
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
        except BaseException as construction_error:
            try:
                await finish()
            except BaseException as cleanup_error:
                logger.error(
                    "Prerequisite response cleanup failed (%s after %s)",
                    type(cleanup_error).__name__,
                    type(construction_error).__name__,
                )
            raise

    return routes


async def _recover_if_idle(deps: AppDeps, topic: str, file_id: str) -> None:
    if topic_lock_busy(deps.locks, topic):
        return
    try:
        lease = await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)
    except Conflict:
        return
    try:
        active_ids = {
            attempt_id
            for attempt_id, active in deps.active_prerequisite_attempts.items()
            if active.topic == topic and active.file_id == file_id
        }
        recover_file_state(
            deps.store,
            deps.profile_store,
            topic,
            file_id,
            active_ids,
            now=_now,
        )
    finally:
        lease.release()


def _now() -> str:
    return datetime.now(UTC).isoformat()
