"""Chat assistant save, trace finalization, and terminal NDJSON events."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from lab.chat_session import append_assistant_message, with_session_context
from lab.contracts import Session
from lab.query_traces import duration

logger = logging.getLogger(__name__)

SaveSessionFn = Callable[[Session], None]


@dataclass
class ChatObserver:
    """Request-scoped partial model output recorded before public enqueue."""

    content: str = ""
    thinking: str = ""
    first_output_at: float | None = None
    generation_started: float = 0.0
    started_monotonic: float = 0.0
    outcome_kind: str = "cancelled"
    provider_model: str | None = None
    provider_context: dict[str, object] | None = None
    provider_error_message: str | None = None
    stream_close_error: dict[str, str] | None = None

    def record_token(self, kind: str, text: str) -> None:
        if self.first_output_at is None:
            self.first_output_at = time.monotonic()
        if kind == "token":
            self.content += text
        else:
            self.thinking += text

    def mark_completed(self, *, model: str | None, context: dict[str, object]) -> None:
        self.outcome_kind = "completed"
        self.provider_model = model
        self.provider_context = context

    def mark_provider_error(self, message: str) -> None:
        self.outcome_kind = "provider_error"
        self.provider_error_message = message

    def mark_premature_eof(self) -> None:
        self.outcome_kind = "premature_eof"

    def mark_generation_failed(self, exc: BaseException) -> None:
        self.outcome_kind = "generation_failed"
        self.provider_error_message = (
            f"Chat failed ({type(exc).__name__}). Check the local model service and retry; your message is saved."
        )

    def mark_cancelled(self) -> None:
        if self.outcome_kind == "cancelled":
            return
        if self.outcome_kind == "completed":
            return
        self.outcome_kind = "cancelled"


@dataclass
class ChatPublicationBundle:
    session: Session
    plan: dict[str, Any]
    trace: Any
    save_session: SaveSessionFn
    requested_model: str
    prompt_context: dict[str, object]
    retrieval_record: dict[str, object]
    trace_id: str


@dataclass
class ChatPublicationOutcome:
    complete: bool
    terminal_events: list[dict[str, Any]] = field(default_factory=list)
    trace_finalize_failed: bool = False
    assistant_saved: bool = False
    published: bool = False
    save_failure: BaseException | None = None


def _assistant_template(
    bundle: ChatPublicationBundle,
    observer: ChatObserver,
) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": observer.content,
        "thinking": observer.thinking,
        "model": observer.provider_model or bundle.requested_model,
        "retrieval": dict(bundle.retrieval_record),
    }


def _generation_ms(observer: ChatObserver) -> float:
    return (time.monotonic() - observer.generation_started) * 1000


def _first_output_ms(observer: ChatObserver) -> float | None:
    if observer.first_output_at is None:
        return None
    return duration((observer.first_output_at - observer.started_monotonic) * 1000)


async def publish_ordinary_chat(
    bundle: ChatPublicationBundle,
    observer: ChatObserver,
) -> ChatPublicationOutcome:
    """Save assistant + trace once; return terminal events (never queued)."""
    assistant = _assistant_template(bundle, observer)
    if observer.outcome_kind == "completed":
        merged_context = {
            **(observer.provider_context or {}),
            "truncated_messages": bundle.prompt_context.get(
                "truncated_messages",
                (observer.provider_context or {}).get("truncated_messages", 0),
            ),
        }
        actual_model = observer.provider_model
        assistant["model"] = actual_model or bundle.requested_model
        session_updated = with_session_context(
            append_assistant_message(bundle.session, assistant),
            merged_context,
        )
        bundle.save_session(session_updated)
        bundle.trace.record["assistant_saved"] = True
        bundle.trace.record["assistant_message_index"] = len(session_updated["messages"]) - 1
        trace_updates = {
            "actual_model": actual_model,
            "context_used": merged_context.get("used"),
            "cleanup_error": observer.stream_close_error,
            "final_context": {
                key: merged_context[key]
                for key in ("used", "limit", "estimated", "truncated_messages")
                if key in merged_context
            },
            "generation_ms": duration(_generation_ms(observer)),
            "first_output_ms": _first_output_ms(observer),
            "output_chars": len(observer.content),
            "thinking_chars": len(observer.thinking),
        }
        done_event = {
            "type": "done",
            "model": assistant["model"],
            "retrieval": dict(bundle.retrieval_record),
            "context": merged_context,
        }
        try:
            bundle.trace.persist("completed", "complete", **trace_updates)
        except Exception as exc:  # noqa: BLE001 - trace failure after save must surface as terminal error
            logger.error("Query trace finalization failed for %s (%s)", bundle.trace_id, type(exc).__name__)
            return ChatPublicationOutcome(
                complete=True,
                assistant_saved=True,
                published=True,
                trace_finalize_failed=True,
                terminal_events=[
                    {
                        "type": "error",
                        "message": "The answer was saved, but its query trace could not be finalized.",
                    }
                ],
            )
        return ChatPublicationOutcome(
            complete=True,
            assistant_saved=True,
            published=True,
            terminal_events=[done_event],
        )

    assistant["incomplete"] = True
    session_updated = append_assistant_message(bundle.session, assistant)
    try:
        bundle.save_session(session_updated)
        bundle.trace.record["assistant_saved"] = True
        bundle.trace.record["assistant_message_index"] = len(session_updated["messages"]) - 1
    except Exception as exc:  # noqa: BLE001 - record failed answer persistence
        logger.error("Assistant save failed for query %s (%s)", bundle.trace_id, type(exc).__name__)
        status = "error"
        stage = "assistant_save"
        error = {
            "stage": "assistant_save",
            "code": "assistant_save_failed",
            "exception_type": type(exc).__name__,
            "summary": "Assistant response could not be saved.",
        }
        terminal = [
            {
                "type": "error",
                "message": f"Chat failed ({type(exc).__name__}). Check the local model service and retry; your message is saved.",
            }
        ]
        return ChatPublicationOutcome(
            complete=False,
            assistant_saved=False,
            published=True,
            terminal_events=terminal,
            save_failure=exc,
        )

    if observer.outcome_kind == "provider_error":
        status, stage, code, summary, message = (
            "error",
            "generation",
            "provider_error",
            "Model reported a generation error.",
            observer.provider_error_message or "Model reported a generation error.",
        )
        error = {
            "stage": stage,
            "code": code,
            "exception_type": "ProviderError",
            "summary": summary,
        }
    elif observer.outcome_kind == "premature_eof":
        status, stage, code, summary = (
            "error",
            "generation",
            "premature_eof",
            "Model stream ended before completion.",
        )
        message = "Model stream ended before completion. Partial output was saved; retry when the local model service is ready."
        error = {
            "stage": stage,
            "code": code,
            "exception_type": "IncompleteStream",
            "summary": summary,
        }
    elif observer.outcome_kind == "generation_failed":
        status, stage, code, summary = (
            "error",
            "generation",
            "generation_failed",
            "Model generation failed.",
        )
        message = observer.provider_error_message or "Chat failed."
        error = {
            "stage": stage,
            "code": code,
            "exception_type": "GenerationFailed",
            "summary": summary,
        }
    else:
        status = "cancelled" if observer.outcome_kind == "cancelled" else "error"
        stage = "generation"
        error = None
        message = None
        if observer.outcome_kind == "cancelled":
            code = None
        else:
            code = "generation_failed"
            error = {
                "stage": "generation",
                "code": "generation_failed",
                "exception_type": "Unknown",
                "summary": "Model generation failed.",
            }
            message = observer.provider_error_message or "Chat failed."

    trace_finalize_failed = False
    if not bundle.trace.done:
        try:
            bundle.trace.persist(
                status,
                stage,
                error=error,
                output_chars=len(observer.content),
                thinking_chars=len(observer.thinking),
                assistant_saved=True,
                assistant_message_index=bundle.trace.record.get("assistant_message_index"),
                generation_ms=duration(_generation_ms(observer)),
                first_output_ms=_first_output_ms(observer),
            )
        except Exception:  # noqa: BLE001 - report trace persistence failure in terminal stream
            trace_finalize_failed = True

    terminal: list[dict[str, Any]] = []
    if message:
        terminal.append({"type": "error", "message": message})
    if trace_finalize_failed:
        terminal.append(
            {
                "type": "error",
                "message": "The answer was saved, but its query trace could not be finalized.",
            }
        )
    return ChatPublicationOutcome(
        complete=False,
        assistant_saved=True,
        published=True,
        trace_finalize_failed=trace_finalize_failed,
        terminal_events=terminal,
    )


async def ensure_ordinary_publication(
    bundle: ChatPublicationBundle,
    observer: ChatObserver,
    *,
    existing: ChatPublicationOutcome | None,
) -> ChatPublicationOutcome:
    """Publish once; reuse an outcome produced inside the execution graph."""
    if existing is not None and existing.published:
        return existing
    if observer.outcome_kind == "cancelled" and not observer.content and not observer.thinking:
        observer.mark_cancelled()
    return await publish_ordinary_chat(bundle, observer)


async def emit_late_graph_failure(
    *,
    publication: ChatPublicationOutcome,
    graph_error: BaseException,
) -> AsyncIterator[dict[str, Any]]:
    if publication.complete and publication.published:
        yield {
            "type": "error",
            "message": (
                f"Chat failed ({type(graph_error).__name__}). Check the local model service and retry; your message is saved."
            ),
        }
