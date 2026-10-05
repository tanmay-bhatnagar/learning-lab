"""Request-bound streaming generation for explicit document-map section summaries."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Literal

from anyio import CancelScope
from fastapi import APIRouter

from lab.document_map_store import get_document_map
from lab.document_map_summary_store import recover_interrupted_attempts, write_summary_attempt
from lab.errors import Conflict, InvalidInput
from lab.runtime_policy import load_runtime_policy
from lab.section_summary import (
    SavedSummary,
    build_section_summary_plan,
    saved_source_metadata,
    validate_source_markers,
)
from lab.web.deps import ActiveSummary, AppDeps
from lab.web.locks import acquire_topic_lock
from lab.web.middleware import FinalizedStreamingResponse
from lab.web.schemas import SectionSummaryInput

logger = logging.getLogger(__name__)
AttemptStatus = Literal["completed", "cancelled", "error"]


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.post("/api/topics/{topic}/files/{file_id}/map/sections/{section_id}/summary")
    async def generate_summary(topic: str, file_id: str, section_id: str, body: SectionSummaryInput):
        lease = await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)
        try:
            active_ids = {
                attempt_id
                for attempt_id, active in deps.active_document_map_summaries.items()
                if active.topic == topic and active.file_id == file_id
            }
            recover_interrupted_attempts(
                deps.store,
                topic,
                file_id,
                active_attempt_ids=active_ids,
                finished_at=datetime.now(UTC).isoformat(),
            )
            current = get_document_map(deps.store, topic, file_id)
            if current["status"] != "ready" or current["map"] is None:
                raise Conflict("Rebuild the document map before generating a summary.")
            map_record = current["map"]
            if map_record["revision"] != body.revision:
                raise Conflict("The selected document map revision changed. Reload it before generating a summary.")
            runtime_policy = load_runtime_policy(deps.config.runtime_policy_path)
            attempt_id = uuid.uuid4().hex
            started_at = datetime.now(UTC).isoformat()
            plan = build_section_summary_plan(
                map_record,
                section_id,
                runtime_policy=runtime_policy,
                model=body.model,
                context_limit=body.context_limit,
                think=body.think,
                attempt_id=attempt_id,
                started_at=started_at,
            )
            attempt = plan["attempt"]
            write_summary_attempt(deps.store, topic, file_id, attempt)
            deps.active_document_map_summaries[attempt_id] = ActiveSummary(
                topic=topic,
                file_id=file_id,
                revision=body.revision,
                section_id=section_id,
            )
            lease.hand_off()
        except BaseException:
            lease.release()
            raise

        stream = None
        content = ""
        thinking = ""
        terminal = False
        closed = False

        def line(event: dict[str, object]) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        def terminal_attempt(status: AttemptStatus, *, error: str | None = None) -> dict[str, object]:
            return {
                **attempt,
                "status": status,
                "finished_at": datetime.now(UTC).isoformat(),
                "content": content,
                "error": error,
            }

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
                        except BaseException as exc:  # noqa: BLE001 - shielded provider cleanup must not strand the topic lease
                            logger.error("Section-summary stream cleanup failed for %s (%s)", attempt_id, type(exc).__name__)
                    if not terminal:
                        cancelled = terminal_attempt("cancelled", error="Generation was cancelled before completion.")
                        try:
                            write_summary_attempt(deps.store, topic, file_id, cancelled)
                            terminal = True
                        except Exception as exc:  # noqa: BLE001 - leave durable generating state for recovery if cancellation persistence fails
                            logger.error("Section-summary cancellation could not be saved for %s (%s)", attempt_id, type(exc).__name__)
                finally:
                    deps.active_document_map_summaries.pop(attempt_id, None)
                    lease.release()

        async def events():
            nonlocal stream, content, thinking, terminal
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
                )
                async for provider_event in stream:
                    kind = provider_event.get("type")
                    if kind in {"token", "thinking"}:
                        text = provider_event.get("text")
                        if not isinstance(text, str):
                            raise InvalidInput("The model stream returned malformed text.")
                        if kind == "token":
                            content += text
                        else:
                            thinking += text
                        yield line({"type": kind, "attempt_id": attempt_id, "text": text})
                        continue
                    if kind == "error":
                        message = provider_event.get("message")
                        text = message if isinstance(message, str) and message else "The model could not complete this summary."
                        failed = terminal_attempt("error", error=text)
                        write_summary_attempt(deps.store, topic, file_id, failed)
                        terminal = True
                        yield line({"type": "error", "attempt_id": attempt_id, "message": text, "attempt": failed})
                        break
                    if kind != "done":
                        raise InvalidInput("The model stream returned an unsupported event.")
                    await _close_stream(stream)
                    stream = None
                    labels = [str(source["label"]) for source in plan["sources"]]
                    validate_source_markers(content, labels)
                    latest = get_document_map(deps.store, topic, file_id)
                    if latest["status"] != "ready" or latest["map"] is None or latest["map"]["revision"] != body.revision:
                        raise Conflict("The source document changed while the summary was generating.")
                    finished_at = datetime.now(UTC).isoformat()
                    actual_model = provider_event.get("model")
                    model_name = actual_model if isinstance(actual_model, str) and actual_model else body.model
                    completed = terminal_attempt("completed")
                    completed["model"] = model_name
                    summary = SavedSummary(
                        id=attempt_id,
                        revision=body.revision,
                        section_id=section_id,
                        section_title=str(plan["section"].get("title", "Untitled section")),
                        content=content,
                        model=model_name,
                        created_at=finished_at,
                        policy_sha256=str(attempt["policy_sha256"]),
                        prompt_version=str(attempt["prompt_version"]),
                        source_sha256=str(attempt["source_sha256"]),
                        sources=saved_source_metadata(plan["sources"]),
                        context_limit=body.context_limit,
                        think=body.think,
                    ).model_dump(mode="json")
                    completed["finished_at"] = finished_at
                    write_summary_attempt(deps.store, topic, file_id, completed, summary=summary)
                    terminal = True
                    yield line(
                        {
                            "type": "done",
                            "attempt_id": attempt_id,
                            "summary": summary,
                            "attempt": completed,
                        }
                    )
                    break
                else:
                    failed = terminal_attempt("error", error="The model stream ended before completion.")
                    write_summary_attempt(deps.store, topic, file_id, failed)
                    terminal = True
                    yield line(
                        {
                            "type": "error",
                            "attempt_id": attempt_id,
                            "message": failed["error"],
                            "attempt": failed,
                        }
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - stream boundary records every provider, validation and persistence failure
                message = str(exc) if isinstance(exc, (Conflict, InvalidInput)) else "The section summary could not be completed."
                failed = terminal_attempt("error", error=message)
                try:
                    write_summary_attempt(deps.store, topic, file_id, failed)
                    terminal = True
                except Exception as save_exc:  # noqa: BLE001 - retain recovery state when terminal write fails
                    logger.error("Section-summary failure could not be saved for %s (%s)", attempt_id, type(save_exc).__name__)
                yield line({"type": "error", "attempt_id": attempt_id, "message": message, "attempt": failed})
            finally:
                await finish()

        return FinalizedStreamingResponse(
            events(),
            on_close=finish,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return routes


async def _close_stream(stream: AsyncIterator[dict[str, object]] | None) -> None:
    if stream is not None and hasattr(stream, "aclose"):
        await stream.aclose()
