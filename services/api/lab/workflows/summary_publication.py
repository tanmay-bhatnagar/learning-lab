"""Section-summary terminal persistence and consumer-emitted NDJSON events."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from lab.document_map_store import get_document_map
from lab.errors import Conflict, InvalidInput
from lab.section_summary import SavedSummary, saved_source_metadata, validate_source_markers

logger = logging.getLogger(__name__)

WriteAttemptFn = Callable[..., dict[str, object]]
NowIsoFn = Callable[[], str]


def _default_now_iso() -> str:
    return datetime.now(UTC).isoformat()


AttemptStatus = Literal["completed", "cancelled", "error"]


@dataclass
class SummaryObserver:
    """Partial model output recorded before public enqueue."""

    content: str = ""
    thinking: str = ""
    outcome_kind: str = "cancelled"
    provider_model: str | None = None
    provider_error_message: str | None = None
    validation_message: str | None = None

    def record(self, kind: str, text: str) -> None:
        if kind == "token":
            self.content += text
        else:
            self.thinking += text

    def mark_completed(self, *, model: str | None) -> None:
        self.outcome_kind = "completed"
        self.provider_model = model

    def mark_provider_error(self, message: str) -> None:
        self.outcome_kind = "provider_error"
        self.provider_error_message = message

    def mark_premature_eof(self) -> None:
        self.outcome_kind = "premature_eof"

    def mark_malformed(self) -> None:
        self.outcome_kind = "malformed"

    def mark_validation_failure(self, message: str) -> None:
        self.outcome_kind = "validation_failure"
        self.validation_message = message

    def mark_cancelled(self) -> None:
        if self.outcome_kind == "completed":
            return
        self.outcome_kind = "cancelled"


@dataclass
class SummaryPublicationBundle:
    store: object
    topic: str
    file_id: str
    section_id: str
    expected_revision: str
    attempt_id: str
    base_attempt: dict[str, object]
    plan: dict[str, object]
    requested_model: str
    context_limit: int
    think: bool | str | None
    write_attempt: WriteAttemptFn
    now_iso: NowIsoFn = field(default=_default_now_iso)


@dataclass
class SummaryPublicationOutcome:
    terminal_persisted: bool = False
    terminal_events: list[dict[str, object]] = field(default_factory=list)


def _terminal_attempt(
    bundle: SummaryPublicationBundle,
    observer: SummaryObserver,
    status: AttemptStatus,
    *,
    error: str | None = None,
    actual_model: str | None = None,
) -> dict[str, object]:
    finished = {
        **bundle.base_attempt,
        "status": status,
        "finished_at": bundle.now_iso(),
        "content": observer.content,
        "error": error,
    }
    if actual_model is not None:
        finished["actual_model"] = actual_model
    return finished


def _user_message_for_failure(observer: SummaryObserver, *, default: str) -> str:
    if observer.outcome_kind == "provider_error":
        message = observer.provider_error_message
        return message if message else "The model could not complete this summary."
    if observer.outcome_kind == "premature_eof":
        return "The model stream ended before completion."
    if observer.outcome_kind == "malformed":
        return "The model stream returned malformed text."
    if observer.outcome_kind == "validation_failure" and observer.validation_message:
        return observer.validation_message
    return default


async def publish_summary_success(
    bundle: SummaryPublicationBundle,
    observer: SummaryObserver,
) -> SummaryPublicationOutcome:
    """Validate sources and map revision, then persist completed summary once."""
    labels = [str(source["label"]) for source in bundle.plan["sources"]]
    try:
        validate_source_markers(observer.content, labels)
        latest = get_document_map(bundle.store, bundle.topic, bundle.file_id)
        if (
            latest["status"] != "ready"
            or latest["map"] is None
            or latest["map"]["revision"] != bundle.expected_revision
        ):
            raise Conflict("The source document changed while the summary was generating.")
        finished_at = bundle.now_iso()
        model_name = observer.provider_model or bundle.requested_model
        completed = _terminal_attempt(bundle, observer, "completed", actual_model=model_name)
        summary = SavedSummary(
            id=bundle.attempt_id,
            revision=bundle.expected_revision,
            section_id=bundle.section_id,
            section_title=str(bundle.plan["section"].get("title", "Untitled section")),
            content=observer.content,
            model=model_name,
            created_at=finished_at,
            policy_sha256=str(bundle.base_attempt["policy_sha256"]),
            prompt_version=str(bundle.base_attempt["prompt_version"]),
            source_sha256=str(bundle.base_attempt["source_sha256"]),
            sources=saved_source_metadata(bundle.plan["sources"]),
            context_limit=bundle.context_limit,
            think=bundle.think,
        ).model_dump(mode="json")
        completed["finished_at"] = finished_at
        bundle.write_attempt(bundle.store, bundle.topic, bundle.file_id, completed, summary=summary)
    except (Conflict, InvalidInput) as exc:
        return await publish_summary_failure(
            bundle,
            observer,
            user_message=str(exc),
            persist_kind="validation_failure",
        )
    except Exception as exc:  # noqa: BLE001 - match legacy stream boundary generic failure
        logger.error(
            "Section-summary success publication failed for %s (%s)",
            bundle.attempt_id,
            type(exc).__name__,
        )
        return await publish_summary_failure(
            bundle,
            observer,
            user_message="The section summary could not be completed.",
            persist_kind="generic",
        )
    return SummaryPublicationOutcome(
        terminal_persisted=True,
        terminal_events=[
            {
                "type": "done",
                "attempt_id": bundle.attempt_id,
                "summary": summary,
                "attempt": completed,
            }
        ],
    )


async def publish_summary_failure(
    bundle: SummaryPublicationBundle,
    observer: SummaryObserver,
    *,
    user_message: str | None = None,
    persist_kind: str | None = None,
) -> SummaryPublicationOutcome:
    """Persist one terminal error attempt when possible and return the public error event."""
    if persist_kind == "validation_failure":
        observer.mark_validation_failure(user_message or "The section summary could not be completed.")
    message = user_message or _user_message_for_failure(
        observer,
        default="The section summary could not be completed.",
    )
    failed = _terminal_attempt(bundle, observer, "error", error=message)
    persisted = False
    try:
        bundle.write_attempt(bundle.store, bundle.topic, bundle.file_id, failed)
        persisted = True
    except Exception as exc:  # noqa: BLE001 - retain generating state when terminal write fails
        logger.error(
            "Section-summary failure could not be saved for %s (%s)",
            bundle.attempt_id,
            type(exc).__name__,
        )
    return SummaryPublicationOutcome(
        terminal_persisted=persisted,
        terminal_events=[
            {
                "type": "error",
                "attempt_id": bundle.attempt_id,
                "message": message,
                "attempt": failed,
            }
        ],
    )


async def publish_summary_from_observer(
    bundle: SummaryPublicationBundle,
    observer: SummaryObserver,
) -> SummaryPublicationOutcome:
    """Route to success or stream failure publication based on observer state."""
    if observer.outcome_kind == "completed":
        return await publish_summary_success(bundle, observer)
    message = _user_message_for_failure(observer, default="The section summary could not be completed.")
    return await publish_summary_failure(bundle, observer, user_message=message)


async def publish_summary_cancelled(
    bundle: SummaryPublicationBundle,
    observer: SummaryObserver,
) -> SummaryPublicationOutcome:
    """Persist cancellation when no terminal outcome was saved yet."""
    if observer.outcome_kind == "completed":
        return SummaryPublicationOutcome(terminal_persisted=True, terminal_events=[])
    observer.mark_cancelled()
    cancelled = _terminal_attempt(
        bundle,
        observer,
        "cancelled",
        error="Generation was cancelled before completion.",
    )
    persisted = False
    try:
        bundle.write_attempt(bundle.store, bundle.topic, bundle.file_id, cancelled)
        persisted = True
    except Exception as exc:  # noqa: BLE001 - leave durable generating state for recovery
        logger.error(
            "Section-summary cancellation could not be saved for %s (%s)",
            bundle.attempt_id,
            type(exc).__name__,
        )
    return SummaryPublicationOutcome(terminal_persisted=persisted, terminal_events=[])
