"""Terminal prerequisite publication, cancellation, and ambiguous-save recovery."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from lab.errors import Conflict, InvalidInput
from lab.prerequisite_store import get_prerequisite_state, recover_interrupted_attempts, write_prerequisite_attempt
from lab.profile_store import ProfileStore
from lab.storage import Store

logger = logging.getLogger(__name__)


class PrerequisitePublicationBundleSource(Protocol):
    store: Store
    profile_store: ProfileStore
    topic_id: str
    file_id: str
    attempt_id: str
    assessment_id: str
    attempt: dict[str, object]
    now: Callable[[], str]


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


AttemptStatus = str


def provider_error_message(_value: object) -> str:
    return "The local model could not complete prerequisite generation."


def terminal_attempt_record(
    attempt: dict[str, object],
    status: AttemptStatus,
    *,
    finished_at: str,
    diagnostic: str | None = None,
) -> dict[str, object]:
    return {**attempt, "status": status, "finished_at": finished_at, "diagnostic": diagnostic}


@dataclass
class PrerequisitePublicationOutcome:
    terminal: bool
    terminal_events: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class PrerequisitePublicationRequest:
    store: Store
    profile_store: ProfileStore
    topic_id: str
    file_id: str
    attempt_id: str
    assessment_id: str
    attempt: dict[str, object]
    now: Callable[[], str]


def publish_stream_failure(
    request: PrerequisitePublicationRequest,
    *,
    message: str,
) -> PrerequisitePublicationOutcome:
    failed = terminal_attempt_record(
        request.attempt,
        "error",
        finished_at=request.now(),
        diagnostic=message,
    )
    write_prerequisite_attempt(request.store, request.topic_id, request.file_id, failed)
    discard_if_unpublished(
        request.profile_store,
        request.store,
        request.topic_id,
        request.file_id,
        request.attempt_id,
        request.assessment_id,
    )
    return PrerequisitePublicationOutcome(
        terminal=True,
        terminal_events=[
            {
                "type": "error",
                "attempt_id": request.attempt_id,
                "message": message,
                "attempt": failed,
            }
        ],
    )


def finalize_success_events(
    *,
    attempt_id: str,
    assessment: dict[str, object],
    proficiency_revision: int,
    completed_attempt: dict[str, object],
) -> PrerequisitePublicationOutcome:
    return PrerequisitePublicationOutcome(
        terminal=True,
        terminal_events=[
            {
                "type": "done",
                "attempt_id": attempt_id,
                "assessment": assessment,
                "proficiency_revision": proficiency_revision,
                "attempt": completed_attempt,
            }
        ],
    )


async def publish_cancelled(
    request: PrerequisitePublicationRequest,
    *,
    already_terminal: bool,
) -> PrerequisitePublicationOutcome:
    if already_terminal:
        return PrerequisitePublicationOutcome(terminal=True, terminal_events=[])
    cancelled = terminal_attempt_record(
        request.attempt,
        "cancelled",
        finished_at=request.now(),
        diagnostic="Generation was cancelled before completion.",
    )
    try:
        write_prerequisite_attempt(request.store, request.topic_id, request.file_id, cancelled)
        discard_if_unpublished(
            request.profile_store,
            request.store,
            request.topic_id,
            request.file_id,
            request.attempt_id,
            request.assessment_id,
        )
        return PrerequisitePublicationOutcome(terminal=True, terminal_events=[])
    except Exception as exc:  # noqa: BLE001 - leave generating state recoverable if persistence fails
        logger.error(
            "Prerequisite cancellation save failed for %s (%s)",
            request.attempt_id,
            type(exc).__name__,
        )
        return PrerequisitePublicationOutcome(terminal=False, terminal_events=[])


async def publish_after_graph_exception(
    request: PrerequisitePublicationRequest,
    exc: BaseException,
) -> PrerequisitePublicationOutcome:
    message = (
        exc.message if isinstance(exc, (Conflict, InvalidInput)) else "Prerequisite generation could not be completed."
    )
    try:
        durable = get_prerequisite_state(request.store, request.topic_id, request.file_id)
    except Exception as read_exc:  # noqa: BLE001 - never delete rows when publication state is unreadable
        logger.error(
            "Prerequisite state check failed for %s (%s)",
            request.attempt_id,
            type(read_exc).__name__,
        )
        return PrerequisitePublicationOutcome(
            terminal=True,
            terminal_events=[
                {
                    "type": "error",
                    "attempt_id": request.attempt_id,
                    "message": "Could not verify whether prerequisites were saved; retry after checking the saved state.",
                }
            ],
        )

    published = published_assessment(durable, request.attempt_id, request.assessment_id)
    if published is not None:
        current_profile = request.profile_store.read_proficiency()
        saved_attempt = next(item for item in durable["attempts"] if item["id"] == request.attempt_id)
        return PrerequisitePublicationOutcome(
            terminal=True,
            terminal_events=[
                {
                    "type": "done",
                    "attempt_id": request.attempt_id,
                    "assessment": published,
                    "proficiency_revision": current_profile["revision"],
                    "attempt": saved_attempt,
                }
            ],
        )

    saved_attempt = next((item for item in durable["attempts"] if item["id"] == request.attempt_id), None)
    terminal = False
    failed: dict[str, object] | None = None
    if saved_attempt is not None and saved_attempt["status"] in {"error", "cancelled", "interrupted"}:
        failed = saved_attempt
        terminal = True
    else:
        failed = terminal_attempt_record(
            request.attempt,
            "error",
            finished_at=request.now(),
            diagnostic=message[:2000],
        )
        try:
            write_prerequisite_attempt(request.store, request.topic_id, request.file_id, failed)
            terminal = True
        except Exception as save_exc:  # noqa: BLE001 - retain recovery state when terminal persistence fails
            logger.error(
                "Prerequisite failure save failed for %s (%s)",
                request.attempt_id,
                type(save_exc).__name__,
            )

    if terminal and failed is not None:
        try:
            discard_if_unpublished(
                request.profile_store,
                request.store,
                request.topic_id,
                request.file_id,
                request.attempt_id,
                request.assessment_id,
            )
        except Exception as cleanup_exc:  # noqa: BLE001 - leave rows intact and let idle recovery retry
            logger.error(
                "Prerequisite profile cleanup failed for %s (%s)",
                request.attempt_id,
                type(cleanup_exc).__name__,
            )
        return PrerequisitePublicationOutcome(
            terminal=True,
            terminal_events=[
                {
                    "type": "error",
                    "attempt_id": request.attempt_id,
                    "message": message,
                    "attempt": failed,
                }
            ],
        )

    return PrerequisitePublicationOutcome(
        terminal=False,
        terminal_events=[
            {
                "type": "error",
                "attempt_id": request.attempt_id,
                "message": "Prerequisites could not be saved; retry after checking the saved state.",
            }
        ],
    )


def publication_request_from_bundle(bundle: PrerequisitePublicationBundleSource) -> PrerequisitePublicationRequest:
    return PrerequisitePublicationRequest(
        store=bundle.store,
        profile_store=bundle.profile_store,
        topic_id=bundle.topic_id,
        file_id=bundle.file_id,
        attempt_id=bundle.attempt_id,
        assessment_id=bundle.assessment_id,
        attempt=bundle.attempt,
        now=bundle.now,
    )
