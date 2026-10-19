"""Chat assistant save, trace finalization, and terminal NDJSON events."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from lab.chat_session import append_assistant_message, with_session_context
from lab.contracts import Session
from lab.evidence_request import MAX_SOURCE_REFERENCES, merge_scoped_sources
from lab.query_traces import duration, retrieval_fields

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
class ChatOptInPublicationBundle:
    session: Session
    initial_plan: dict[str, Any]
    trace: Any
    save_session: SaveSessionFn
    requested_model: str
    retrieval_record: dict[str, object]
    trace_id: str
    file_ids: list[str]
    search_result: dict[str, object]
    total_retrieval_ms: float
    generation_started: float
    started_monotonic: float
    initial_chunks: tuple[dict[str, object], ...] = ()
    evidence_scope: tuple[str, ...] = ()
    latest_search_result: dict[str, object] | None = None


@dataclass
class ChatOptInObserver:
    content: str = ""
    thinking: str = ""
    first_output_at: float | None = None
    generation_started: float = 0.0
    started_monotonic: float = 0.0
    workflow_error: tuple[str, str] | None = None
    complete: bool = False
    model_finished: bool = False
    final_plan: dict[str, Any] | None = None
    final_metadata: dict[str, object] | None = None
    provider_model: str | None = None
    provider_context: dict[str, object] | None = None
    direct_answer_text: str | None = None
    decision_model: str | None = None
    decision_context: dict[str, object] | None = None
    search_query: str | None = None
    lookup_returned: tuple[dict[str, object], ...] = ()
    lookup_novel: tuple[dict[str, object], ...] = ()
    pending_final_chunk_ids: list[str] | None = None
    pending_retained_new_chunk_ids: list[str] | None = None
    stream_close_error: dict[str, str] | None = None
    cancelled: bool = False
    workflow_stage: str = "generation"

    def record_token(self, kind: str, text: str) -> None:
        if self.first_output_at is None:
            self.first_output_at = time.monotonic()
        if kind == "token":
            self.content += text
        else:
            self.thinking += text

    def set_workflow_error(self, code: str, message: str) -> None:
        self.workflow_error = (code, message)
        self.complete = False

    def apply_plan(self, plan: dict[str, Any], metadata: dict[str, object]) -> None:
        self.final_plan = plan
        self.final_metadata = dict(metadata)

    def mark_evidence_complete(
        self,
        *,
        plan: dict[str, Any],
        metadata: dict[str, object],
        model: str | None,
        context: dict[str, object] | None,
    ) -> None:
        self.final_plan = plan
        self.final_metadata = dict(metadata)
        self.provider_model = model
        self.provider_context = context
        self.model_finished = True

    def mark_cancelled(self) -> None:
        self.cancelled = True
        self.model_finished = False
        self.complete = False


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


def _ordinary_error_terminal(
    observer: ChatObserver,
) -> tuple[list[dict[str, Any]], str, str, dict[str, str] | None, str | None]:
    if observer.outcome_kind == "provider_error":
        message = observer.provider_error_message or "Model reported a generation error."
        error = {
            "stage": "generation",
            "code": "provider_error",
            "exception_type": "ProviderError",
            "summary": "Model reported a generation error.",
        }
        return [{"type": "error", "message": message}], "error", "generation", error, message
    if observer.outcome_kind == "premature_eof":
        message = "Model stream ended before completion. Partial output was saved; retry when the local model service is ready."
        error = {
            "stage": "generation",
            "code": "premature_eof",
            "exception_type": "IncompleteStream",
            "summary": "Model stream ended before completion.",
        }
        return [{"type": "error", "message": message}], "error", "generation", error, message
    if observer.outcome_kind == "generation_failed":
        message = observer.provider_error_message or "Chat failed."
        error = {
            "stage": "generation",
            "code": "generation_failed",
            "exception_type": "GenerationFailed",
            "summary": "Model generation failed.",
        }
        return [{"type": "error", "message": message}], "error", "generation", error, message
    if observer.outcome_kind == "cancelled":
        return [], "cancelled", "generation", None, None
    message = observer.provider_error_message or "Chat failed."
    error = {
        "stage": "generation",
        "code": "generation_failed",
        "exception_type": "Unknown",
        "summary": "Model generation failed.",
    }
    return [{"type": "error", "message": message}], "error", "generation", error, message


async def prepare_ordinary_publication(
    bundle: ChatPublicationBundle,
    observer: ChatObserver,
) -> ChatPublicationOutcome:
    """Decide outcome and terminal events without persisting a complete answer."""
    if observer.outcome_kind == "completed":
        merged_context = {
            **(observer.provider_context or {}),
            "truncated_messages": bundle.prompt_context.get(
                "truncated_messages",
                (observer.provider_context or {}).get("truncated_messages", 0),
            ),
        }
        actual_model = observer.provider_model
        assistant_model = actual_model or bundle.requested_model
        done_event = {
            "type": "done",
            "model": assistant_model,
            "retrieval": dict(bundle.retrieval_record),
            "context": merged_context,
        }
        return ChatPublicationOutcome(complete=True, terminal_events=[done_event])
    terminal, *_rest = _ordinary_error_terminal(observer)
    return ChatPublicationOutcome(complete=False, terminal_events=terminal)


async def commit_ordinary_publication(
    bundle: ChatPublicationBundle,
    observer: ChatObserver,
    *,
    prepared: ChatPublicationOutcome | None,
    terminal_delivered: bool,
) -> ChatPublicationOutcome:
    """Single shielded persist for this request; ``terminal_delivered`` gates complete saves."""
    if bundle.trace.record.get("assistant_saved"):
        if prepared is not None:
            prepared.assistant_saved = True
            prepared.published = True
            return prepared
        return ChatPublicationOutcome(
            complete=False,
            assistant_saved=True,
            published=True,
        )
    deliver_complete = (
        terminal_delivered and prepared is not None and prepared.complete and observer.outcome_kind == "completed"
    )
    assistant = _assistant_template(bundle, observer)
    if deliver_complete:
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

    terminal, status, stage, error, message = _ordinary_error_terminal(observer)
    if not terminal_delivered and prepared is not None and prepared.complete and observer.outcome_kind == "completed":
        status, stage, error, message = "cancelled", "generation", None, None
        terminal = []

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

    outcome_terminal: list[dict[str, Any]] = list(terminal)
    if message and not outcome_terminal:
        outcome_terminal.append({"type": "error", "message": message})
    if trace_finalize_failed:
        outcome_terminal.append(
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
        terminal_events=outcome_terminal,
    )


def _optin_generation_ms(observer: ChatOptInObserver) -> float:
    return (time.monotonic() - observer.generation_started) * 1000


def _optin_first_output_ms(observer: ChatOptInObserver) -> float | None:
    if observer.first_output_at is None:
        return None
    return duration((observer.first_output_at - observer.started_monotonic) * 1000)


async def prepare_optin_publication(
    bundle: ChatOptInPublicationBundle,
    observer: ChatOptInObserver,
) -> ChatPublicationOutcome:
    """Decide opt-in outcome and terminal events without persisting a complete answer."""
    metadata = dict(observer.final_metadata or bundle.trace.record.get("evidence_search") or {})
    retrieval_record = dict(bundle.retrieval_record)
    if observer.final_plan is not None:
        retrieval_record = dict(observer.final_plan["retrieval_record"])
    retrieval_record["evidence_search"] = metadata
    if observer.model_finished and observer.workflow_error is None:
        actual_model = observer.provider_model
        merged_context = {
            **(observer.provider_context or {}),
            "truncated_messages": observer.final_plan["prompt_context"].get("truncated_messages", 0)
            if observer.final_plan
            else 0,
        }
        done_event = {
            "type": "done",
            "model": actual_model or bundle.requested_model,
            "retrieval": retrieval_record,
            "context": merged_context,
        }
        return ChatPublicationOutcome(complete=True, terminal_events=[done_event])
    if observer.workflow_error is not None:
        _code, message = observer.workflow_error
        return ChatPublicationOutcome(complete=False, terminal_events=[{"type": "error", "message": message}])
    return ChatPublicationOutcome(complete=False, terminal_events=[])


async def commit_optin_publication(
    bundle: ChatOptInPublicationBundle,
    observer: ChatOptInObserver,
    *,
    prepared: ChatPublicationOutcome | None,
    terminal_delivered: bool,
) -> ChatPublicationOutcome:
    """Single shielded persist for an opt-in request."""
    if bundle.trace.record.get("assistant_saved"):
        if prepared is not None:
            prepared.assistant_saved = True
            prepared.published = True
            return prepared
        return ChatPublicationOutcome(
            complete=False,
            assistant_saved=True,
            published=True,
        )
    deliver_complete = (
        terminal_delivered
        and prepared is not None
        and prepared.complete
        and observer.model_finished
        and observer.workflow_error is None
    )
    if deliver_complete:
        done_event = prepared.terminal_events[0] if prepared and prepared.terminal_events else {"type": "done"}
        return await _commit_optin_complete(bundle, observer, done_event=done_event)
    trace_evidence = bundle.trace.record.get("evidence_search")
    metadata = dict(
        trace_evidence
        if isinstance(trace_evidence, dict)
        else (observer.final_metadata if isinstance(observer.final_metadata, dict) else {})
    )
    retrieval_record = dict(bundle.retrieval_record)
    if observer.final_plan is not None:
        retrieval_record = dict(observer.final_plan["retrieval_record"])
    retrieval_record["evidence_search"] = metadata
    assistant: dict[str, object] = {
        "role": "assistant",
        "content": observer.content,
        "thinking": observer.thinking,
        "model": observer.provider_model or bundle.requested_model,
        "retrieval": retrieval_record,
    }
    client_disconnected = not terminal_delivered and (
        (prepared is not None and prepared.complete)
        or (prepared is None and bool(observer.content or observer.thinking))
    )
    if client_disconnected:
        observer.workflow_error = None
        observer.mark_cancelled()
        metadata["outcome"] = "cancelled"
        retrieval_record["evidence_search"] = metadata
        assistant["retrieval"] = dict(retrieval_record)
        if isinstance(bundle.trace.record.get("evidence_search"), dict):
            bundle.trace.record["evidence_search"]["outcome"] = "cancelled"

    if observer.workflow_error is not None and not observer.cancelled:
        code, message = observer.workflow_error
        metadata["outcome"] = "error"
        assistant["retrieval"] = dict(retrieval_record)
        assistant["incomplete"] = True
        session_updated = append_assistant_message(bundle.session, assistant)
        try:
            bundle.save_session(session_updated)
            bundle.trace.record["assistant_saved"] = True
            bundle.trace.record["assistant_message_index"] = len(session_updated["messages"]) - 1
        except Exception as exc:  # noqa: BLE001 - record failed answer persistence
            logger.error("Assistant save failed for query %s (%s)", bundle.trace_id, type(exc).__name__)
            return ChatPublicationOutcome(
                complete=False,
                assistant_saved=False,
                published=True,
                terminal_events=[
                    {
                        "type": "error",
                        "message": f"Chat failed ({type(exc).__name__}). Check the local model service and retry; your message is saved.",
                    }
                ],
                save_failure=exc,
            )
        error = {
            "stage": "generation",
            "code": code or "evidence_failed",
            "exception_type": "EvidenceWorkflowError",
            "summary": "The additional evidence workflow could not complete.",
        }
        trace_finalize_failed = False
        try:
            bundle.trace.persist(
                "error",
                "generation",
                error=error,
                output_chars=len(observer.content),
                thinking_chars=len(observer.thinking),
                assistant_saved=True,
                assistant_message_index=bundle.trace.record.get("assistant_message_index"),
                generation_ms=duration(_optin_generation_ms(observer)),
                first_output_ms=_optin_first_output_ms(observer),
            )
        except Exception:  # noqa: BLE001 - report trace persistence failure in terminal stream
            trace_finalize_failed = True
        terminal: list[dict[str, Any]] = [{"type": "error", "message": message}]
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

    if observer.cancelled:
        metadata["outcome"] = "cancelled"
    else:
        evidence_meta = bundle.trace.record.get("evidence_search")
        if isinstance(evidence_meta, dict) and isinstance(evidence_meta.get("outcome"), str):
            metadata["outcome"] = str(evidence_meta["outcome"])
        else:
            metadata["outcome"] = "error"
    retrieval_record["evidence_search"] = metadata
    assistant["retrieval"] = dict(retrieval_record)
    assistant["incomplete"] = True
    assistant["retrieval"] = dict(retrieval_record)
    session_updated = append_assistant_message(bundle.session, assistant)
    try:
        bundle.save_session(session_updated)
        bundle.trace.record["assistant_saved"] = True
        bundle.trace.record["assistant_message_index"] = len(session_updated["messages"]) - 1
    except Exception as exc:  # noqa: BLE001 - record failed answer persistence
        logger.error("Assistant save failed for query %s (%s)", bundle.trace_id, type(exc).__name__)
        return ChatPublicationOutcome(
            complete=False,
            assistant_saved=False,
            published=True,
            terminal_events=[
                {
                    "type": "error",
                    "message": f"Chat failed ({type(exc).__name__}). Check the local model service and retry; your message is saved.",
                }
            ],
            save_failure=exc,
        )
    status = "cancelled" if metadata.get("outcome") == "cancelled" else "error"
    stage = observer.workflow_stage or "generation"
    bundle.trace.persist(
        status,
        stage,
        error=None
        if observer.cancelled
        else {
            "stage": "generation",
            "code": "generation_failed",
            "exception_type": "Unknown",
            "summary": "Model generation failed.",
        },
        output_chars=len(observer.content),
        thinking_chars=len(observer.thinking),
        assistant_saved=True,
        assistant_message_index=bundle.trace.record.get("assistant_message_index"),
        generation_ms=duration(_optin_generation_ms(observer)),
        first_output_ms=_optin_first_output_ms(observer),
    )
    return ChatPublicationOutcome(
        complete=False,
        assistant_saved=True,
        published=True,
        terminal_events=[],
    )


async def _commit_optin_complete(
    bundle: ChatOptInPublicationBundle,
    observer: ChatOptInObserver,
    *,
    done_event: dict[str, Any],
) -> ChatPublicationOutcome:
    metadata = dict(observer.final_metadata or bundle.trace.record.get("evidence_search") or {})
    retrieval_record = dict(bundle.retrieval_record)
    if observer.final_plan is not None:
        retrieval_record = dict(observer.final_plan["retrieval_record"])
    retrieval_record["evidence_search"] = metadata
    assistant: dict[str, object] = {
        "role": "assistant",
        "content": observer.content,
        "thinking": observer.thinking,
        "model": observer.provider_model or bundle.requested_model,
        "retrieval": retrieval_record,
    }
    actual_model = observer.provider_model
    assistant["model"] = actual_model or bundle.requested_model
    merged_context = {
        **(observer.provider_context or {}),
        "truncated_messages": observer.final_plan["prompt_context"].get("truncated_messages", 0)
        if observer.final_plan
        else 0,
    }
    if observer.final_plan is not None and bundle.latest_search_result is not None:
        combined_hits = merge_scoped_sources(
            bundle.initial_chunks,
            bundle.latest_search_result.get("hits", []),
            selected_file_ids=set(bundle.evidence_scope),
            max_sources=MAX_SOURCE_REFERENCES,
        )
        bundle.trace.record = retrieval_fields(
            bundle.trace.record,
            selected_file_ids=list(dict.fromkeys(bundle.file_ids)),
            search_result={**bundle.latest_search_result, "hits": list(combined_hits)},
            retained_ids={item["chunk_id"] for item in observer.final_plan["citations"]},
            citations=observer.final_plan["citations"],
            retrieval_ms=bundle.total_retrieval_ms,
        )
        bundle.trace.record["evidence_search"] = metadata
    try:
        session_updated = with_session_context(
            append_assistant_message(bundle.session, assistant),
            merged_context,
        )
        bundle.save_session(session_updated)
        bundle.trace.record["assistant_saved"] = True
        bundle.trace.record["assistant_message_index"] = len(session_updated["messages"]) - 1
    except Exception as exc:  # noqa: BLE001 - complete save failure becomes incomplete + generation_failed trace
        logger.error("Assistant save failed for query %s (%s)", bundle.trace_id, type(exc).__name__)
        assistant["incomplete"] = True
        metadata["outcome"] = "error"
        assistant["retrieval"] = dict(retrieval_record)
        session_updated = append_assistant_message(bundle.session, assistant)
        bundle.save_session(session_updated)
        bundle.trace.record["assistant_saved"] = True
        bundle.trace.record["assistant_message_index"] = len(session_updated["messages"]) - 1
        error = {
            "stage": "generation",
            "code": "generation_failed",
            "exception_type": type(exc).__name__,
            "summary": "Model generation failed.",
        }
        bundle.trace.persist(
            "error",
            "generation",
            error=error,
            output_chars=len(observer.content),
            thinking_chars=len(observer.thinking),
            assistant_saved=True,
            assistant_message_index=bundle.trace.record.get("assistant_message_index"),
            generation_ms=duration(_optin_generation_ms(observer)),
            first_output_ms=_optin_first_output_ms(observer),
        )
        return ChatPublicationOutcome(
            complete=False,
            assistant_saved=True,
            published=True,
            terminal_events=[
                {
                    "type": "error",
                    "message": f"Chat failed ({type(exc).__name__}). Check the local model service and retry; your message is saved.",
                }
            ],
        )
    trace_updates = {
        "actual_model": actual_model,
        "context_used": merged_context.get("used"),
        "cleanup_error": observer.stream_close_error,
        "final_context": {
            key: merged_context[key]
            for key in ("used", "limit", "estimated", "truncated_messages")
            if key in merged_context
        },
        "generation_ms": duration(_optin_generation_ms(observer)),
        "first_output_ms": _optin_first_output_ms(observer),
        "output_chars": len(observer.content),
        "thinking_chars": len(observer.thinking),
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
    observer.complete = True
    return ChatPublicationOutcome(
        complete=True,
        assistant_saved=True,
        published=True,
        terminal_events=[done_event],
    )


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
