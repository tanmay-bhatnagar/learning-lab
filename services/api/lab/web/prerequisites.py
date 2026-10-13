"""HTTP lifecycle for on-demand, CV-grounded section prerequisite assessments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Literal

from anyio import CancelScope
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from lab.document_map_store import get_document_map
from lab.errors import Conflict, InvalidInput, NotFound
from lab.prerequisite_store import (
    current_assessment,
    get_prerequisite_state,
    recover_interrupted_attempts,
    write_prerequisite_attempt,
)
from lab.prerequisites import MAX_RESPONSE_BYTES, build_prerequisite_plan, validate_prerequisite_response
from lab.runtime_policy import load_runtime_policy
from lab.web.deps import ActivePrerequisite, AppDeps
from lab.web.locks import acquire_topic_lock, topic_lock_busy
from lab.web.middleware import FinalizedStreamingResponse

logger = logging.getLogger(__name__)
AttemptStatus = Literal["completed", "cancelled", "error"]


class PrerequisiteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1, max_length=200)
    context_limit: int = Field(default=32768, ge=1024, le=32768)
    think: bool | Literal["low", "medium", "high"] | None = None
    goal: str | None = Field(default=None, max_length=2000)


def router(deps: AppDeps) -> APIRouter:
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
            _recover_file_state(deps, topic, file_id, active_ids)
            current = get_document_map(deps.store, topic, file_id)
            if current["status"] != "ready" or current["map"] is None:
                raise Conflict("Build the current document map before generating prerequisites.")
            map_record = current["map"]
            if map_record["revision"] != body.revision:
                raise Conflict("The selected document map revision changed. Reload it before generating prerequisites.")

            profile = deps.profile_store.read_profile()
            selected = next((item for item in profile["cvs"] if item["id"] == profile["active_cv_id"]), None)
            if selected is None or selected["status"] != "ready" or selected["revoked"]:
                raise Conflict("Select a successfully extracted, non-revoked CV before generating prerequisites.")
            cv_text = deps.profile_store.read_extracted_text(selected["id"])
            if hashlib.sha256(cv_text.encode("utf-8")).hexdigest() != selected["extracted_sha256"]:
                raise Conflict("The selected CV text changed. Reload the CV and retry.")

            runtime_policy = load_runtime_policy(deps.config.runtime_policy_path)
            attempt_id = uuid.uuid4().hex
            assessment_id = uuid.uuid4().hex
            started_at = _now()
            plan = build_prerequisite_plan(
                map_record,
                section_id,
                selected_cv=selected,
                cv_text=cv_text,
                runtime_policy=runtime_policy,
                goal=body.goal,
                model=body.model,
                context_limit=body.context_limit,
                think=body.think,
                assessment_id=assessment_id,
                attempt_id=attempt_id,
                started_at=started_at,
            )
            provenance = plan["provenance"]
            attempt = {
                "id": attempt_id,
                "assessment_id": assessment_id,
                "topic_id": topic,
                "file_id": file_id,
                "map_revision": body.revision,
                "section_id": section_id,
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
                    "model": body.model,
                },
                "diagnostic": None,
            }
            write_prerequisite_attempt(deps.store, topic, file_id, attempt)
            deps.active_prerequisite_attempts[attempt_id] = ActivePrerequisite(
                topic=topic, file_id=file_id, revision=body.revision, section_id=section_id
            )
            lease.hand_off()
        except BaseException:
            lease.release()
            raise

        stream = None
        content = ""
        content_bytes = 0
        terminal = False
        closed = False

        def line(event: dict[str, object]) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        def terminal_attempt(status: AttemptStatus, diagnostic: str | None = None) -> dict[str, object]:
            return {**attempt, "status": status, "finished_at": _now(), "diagnostic": diagnostic}

        async def finish() -> None:
            nonlocal stream, terminal, closed
            if closed:
                return
            closed = True
            with CancelScope(shield=True):
                try:
                    if stream is not None and hasattr(stream, "aclose"):
                        try:
                            await stream.aclose()
                        except BaseException as exc:  # noqa: BLE001 - provider cleanup must not strand the topic lock
                            logger.error(
                                "Prerequisite stream cleanup failed for %s (%s)", attempt_id, type(exc).__name__
                            )
                    if not terminal:
                        cancelled = terminal_attempt("cancelled", "Generation was cancelled before completion.")
                        try:
                            write_prerequisite_attempt(deps.store, topic, file_id, cancelled)
                            terminal = True
                            _discard_if_unpublished(deps, topic, file_id, attempt_id, assessment_id)
                        except Exception as exc:  # noqa: BLE001 - leave generating state recoverable if persistence fails
                            logger.error(
                                "Prerequisite cancellation save failed for %s (%s)", attempt_id, type(exc).__name__
                            )
                finally:
                    deps.active_prerequisite_attempts.pop(attempt_id, None)
                    lease.release()

        async def events():
            nonlocal stream, content, content_bytes, terminal
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
                stream = deps.model_backend.stream_chat(
                    plan["messages"],
                    body.model,
                    body.think,
                    body.context_limit,
                    context_metadata=plan["prompt_context"],
                    generation_lock=deps.model_generation_lock,
                    response_schema=plan["response_schema"],
                )
                async for provider_event in stream:
                    kind = provider_event.get("type")
                    if kind == "thinking":
                        continue
                    if kind == "token":
                        text = provider_event.get("text")
                        if not isinstance(text, str):
                            raise InvalidInput("The model stream returned malformed text.")
                        text_bytes = len(text.encode("utf-8"))
                        if content_bytes + text_bytes > MAX_RESPONSE_BYTES:
                            raise InvalidInput("The model response exceeded the allowed size; retry generation.")
                        content += text
                        content_bytes += text_bytes
                        yield line({"type": "progress", "attempt_id": attempt_id, "phase": "generating"})
                        continue
                    if kind == "error":
                        message = _provider_error(provider_event.get("message"))
                        failed = terminal_attempt("error", message)
                        write_prerequisite_attempt(deps.store, topic, file_id, failed)
                        terminal = True
                        _discard_if_unpublished(deps, topic, file_id, attempt_id, assessment_id)
                        yield line({"type": "error", "attempt_id": attempt_id, "message": message, "attempt": failed})
                        break
                    if kind != "done":
                        raise InvalidInput("The model stream returned an unsupported event.")
                    await _close_stream(stream)
                    stream = None
                    latest_map = get_document_map(deps.store, topic, file_id)
                    if (
                        latest_map["status"] != "ready"
                        or latest_map["map"] is None
                        or latest_map["map"]["revision"] != body.revision
                    ):
                        raise Conflict("The source document changed while prerequisites were generating.")
                    latest_profile = deps.profile_store.read_profile()
                    latest_cv = next(
                        (item for item in latest_profile["cvs"] if item["id"] == latest_profile["active_cv_id"]), None
                    )
                    latest_text = deps.profile_store.read_extracted_text(selected["id"])
                    latest_hash = hashlib.sha256(latest_text.encode("utf-8")).hexdigest()
                    if (
                        latest_cv is None
                        or latest_cv["id"] != selected["id"]
                        or latest_cv["status"] != "ready"
                        or latest_cv["revoked"]
                        or latest_cv["extracted_sha256"] != provenance["cv_text_sha256"]
                        or latest_hash != provenance["cv_text_sha256"]
                    ):
                        raise Conflict("The selected CV changed while prerequisites were generating; retry.")
                    parsed = validate_prerequisite_response(
                        content,
                        sources=plan["sources"],
                        cv_text=cv_text,
                        assessment_id=assessment_id,
                    )
                    finished_at = _now()
                    assessment = {
                        "attempt_id": attempt_id,
                        "assessment_id": assessment_id,
                        "topic_id": topic,
                        "file_id": file_id,
                        "map_revision": body.revision,
                        "section_id": section_id,
                        "cv_id": selected["id"],
                        "cv_text_sha256": provenance["cv_text_sha256"],
                        "source_sha256": provenance["source_sha256"],
                        **parsed,
                        "sources": plan["source_metadata"],
                        "finished_at": finished_at,
                    }
                    completed = {**attempt, "status": "completed", "finished_at": finished_at, "diagnostic": None}
                    proficiency = deps.profile_store.register_model_requirements(
                        parsed["requirements"],
                        topic_id=topic,
                        assessment_id=assessment_id,
                        selected_cv_id=selected["id"],
                        selected_cv_text_sha256=provenance["cv_text_sha256"],
                    )
                    write_prerequisite_attempt(deps.store, topic, file_id, completed, assessment=assessment)
                    terminal = True
                    yield line(
                        {
                            "type": "done",
                            "attempt_id": attempt_id,
                            "assessment": assessment,
                            "proficiency_revision": proficiency["revision"],
                            "attempt": completed,
                        }
                    )
                    break
                else:
                    message = "The model stream ended before completion."
                    failed = terminal_attempt("error", message)
                    write_prerequisite_attempt(deps.store, topic, file_id, failed)
                    terminal = True
                    _discard_if_unpublished(deps, topic, file_id, attempt_id, assessment_id)
                    yield line({"type": "error", "attempt_id": attempt_id, "message": message, "attempt": failed})
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - stream boundary records validation/provider/storage failures safely
                message = (
                    exc.message
                    if isinstance(exc, (Conflict, InvalidInput))
                    else "Prerequisite generation could not be completed."
                )
                try:
                    durable = get_prerequisite_state(deps.store, topic, file_id)
                except Exception as read_exc:  # noqa: BLE001 - never delete rows when publication state is unreadable
                    logger.error("Prerequisite state check failed for %s (%s)", attempt_id, type(read_exc).__name__)
                    yield line(
                        {
                            "type": "error",
                            "attempt_id": attempt_id,
                            "message": "Could not verify whether prerequisites were saved; retry after checking the saved state.",
                        }
                    )
                else:
                    published = _published_assessment(durable, attempt_id, assessment_id)
                    if published is not None:
                        terminal = True
                        current_profile = deps.profile_store.read_proficiency()
                        saved_attempt = next(item for item in durable["attempts"] if item["id"] == attempt_id)
                        yield line(
                            {
                                "type": "done",
                                "attempt_id": attempt_id,
                                "assessment": published,
                                "proficiency_revision": current_profile["revision"],
                                "attempt": saved_attempt,
                            }
                        )
                    else:
                        saved_attempt = next((item for item in durable["attempts"] if item["id"] == attempt_id), None)
                        if saved_attempt is not None and saved_attempt["status"] in {
                            "error",
                            "cancelled",
                            "interrupted",
                        }:
                            failed = saved_attempt
                            terminal = True
                        else:
                            failed = terminal_attempt("error", message[:2000])
                            try:
                                write_prerequisite_attempt(deps.store, topic, file_id, failed)
                                terminal = True
                            except Exception as save_exc:  # noqa: BLE001 - retain recovery state when terminal persistence fails
                                logger.error(
                                    "Prerequisite failure save failed for %s (%s)", attempt_id, type(save_exc).__name__
                                )
                        if terminal:
                            try:
                                _discard_if_unpublished(deps, topic, file_id, attempt_id, assessment_id)
                            except Exception as cleanup_exc:  # noqa: BLE001 - leave rows intact and let idle recovery retry
                                logger.error(
                                    "Prerequisite profile cleanup failed for %s (%s)",
                                    attempt_id,
                                    type(cleanup_exc).__name__,
                                )
                            yield line(
                                {"type": "error", "attempt_id": attempt_id, "message": message, "attempt": failed}
                            )
                        else:
                            yield line(
                                {
                                    "type": "error",
                                    "attempt_id": attempt_id,
                                    "message": "Prerequisites could not be saved; retry after checking the saved state.",
                                }
                            )
            finally:
                await finish()

        return FinalizedStreamingResponse(
            events(),
            on_close=finish,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

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
        _recover_file_state(deps, topic, file_id, active_ids)
    finally:
        lease.release()


def _recover_file_state(deps: AppDeps, topic: str, file_id: str, active_ids: set[str]) -> None:
    recover_interrupted_attempts(deps.store, topic, file_id, active_attempt_ids=active_ids, finished_at=_now())
    state = get_prerequisite_state(deps.store, topic, file_id)
    for attempt in state["attempts"]:
        if attempt["status"] in {"error", "cancelled", "interrupted"}:
            _discard_if_unpublished(deps, topic, file_id, attempt["id"], attempt["assessment_id"])


def _discard_if_unpublished(deps: AppDeps, topic: str, file_id: str, attempt_id: str, assessment_id: str) -> None:
    state = get_prerequisite_state(deps.store, topic, file_id)
    attempt = next((item for item in state["attempts"] if item["id"] == attempt_id), None)
    if attempt is None or attempt["status"] not in {"error", "cancelled", "interrupted"}:
        return
    if _assessment_id_is_published(state, assessment_id):
        return
    deps.profile_store.discard_unpublished_pending(topic_id=topic, assessment_id=assessment_id)


def _published_assessment(state: dict[str, object], attempt_id: str, assessment_id: str) -> dict[str, object] | None:
    assessments = state["assessments"]
    return next(
        (item for item in assessments if item["attempt_id"] == attempt_id and item["assessment_id"] == assessment_id),
        None,
    )


def _assessment_id_is_published(state: dict[str, object], assessment_id: str) -> bool:
    return any(item["assessment_id"] == assessment_id for item in state["assessments"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _provider_error(_value: object) -> str:
    return "The local model could not complete prerequisite generation."


async def _close_stream(stream: AsyncIterator[dict[str, object]] | None) -> None:
    if stream is not None and hasattr(stream, "aclose"):
        await stream.aclose()
