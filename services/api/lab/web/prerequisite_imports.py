"""Explicit completed-prerequisite handoff into an existing main conversation."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from lab.conversation_profile import get_conversation_profile, save_conversation_profile
from lab.document_map_store import get_document_map
from lab.errors import Conflict, CorruptData, NotFound
from lab.learner_profile import proficiency_context
from lab.prerequisite_import import build_prerequisite_import, existing_prerequisite_import
from lab.prerequisite_store import get_prerequisite_state
from lab.web.deps import AppDeps
from lab.web.locks import acquire_topic_lock


class PrerequisiteImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    file_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    assessment_id: str = Field(min_length=1, max_length=100)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    section_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=0)


def _section_title(sections: list[dict], section_id: str) -> str | None:
    for section in sections:
        if section["id"] == section_id:
            return section["title"]
        nested = _section_title(section.get("children", []), section_id)
        if nested is not None:
            return nested
    return None


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.post("/api/topics/{topic}/conversations/{conversation_id}/prerequisite-imports")
    async def import_prerequisites(topic: str, conversation_id: str, body: PrerequisiteImportInput):
        lease = await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)
        try:
            session = deps.store.session(topic, conversation_id)
            preference = get_conversation_profile(deps.store, topic, conversation_id)
            if preference["revision"] != body.expected_revision:
                raise Conflict("Conversation preferences changed; reload before adding prerequisites.")
            state = get_prerequisite_state(deps.store, topic, body.file_id)
            assessment = next(
                (item for item in state["assessments"] if item["assessment_id"] == body.assessment_id), None
            )
            if assessment is None:
                raise NotFound("The completed prerequisite assessment is unavailable.")
            if assessment["map_revision"] != body.revision or assessment["section_id"] != body.section_id:
                raise Conflict("The selected prerequisite assessment source identity changed.")
            attempt = next(item for item in state["attempts"] if item["id"] == assessment["attempt_id"])
            goal = attempt["provenance"]["goal"]
            if not isinstance(goal, str):
                raise CorruptData("Saved prerequisite learning goal is malformed.")
            prior = existing_prerequisite_import(
                session, conversation_id, assessment_id=body.assessment_id, file_id=body.file_id
            )
            if prior is None:
                response = get_document_map(deps.store, topic, body.file_id)
                if (
                    response["status"] != "ready"
                    or response["map"] is None
                    or response["map"]["revision"] != body.revision
                ):
                    raise Conflict("Reload the current document map before adding prerequisites.")
                title = _section_title(response["map"]["sections"], body.section_id)
                if title is None:
                    raise NotFound("The source section is unavailable.")
                message = build_prerequisite_import(
                    conversation_id,
                    assessment=assessment,
                    section_title=title,
                    goal=goal,
                    model=attempt["provenance"]["model"],
                    learner_context=proficiency_context(
                        deps.profile_store.read_proficiency(), topic_id=topic, active_assessment_id=body.assessment_id
                    ),
                    imported_at=datetime.now(UTC).isoformat(),
                )
                updated = {**session, "messages": [*session.get("messages", []), message]}
                deps.store.save_session(topic, updated, conversation_id)
            else:
                message = prior
                updated = session
            focus = {
                "file_id": body.file_id,
                "assessment_id": body.assessment_id,
                "map_revision": body.revision,
                "section_id": body.section_id,
                "goal": goal,
            }
            if preference["active_assessment"] != focus:
                preference = save_conversation_profile(
                    deps.store,
                    topic,
                    conversation_id,
                    updates={"active_assessment": focus},
                    expected_revision=body.expected_revision,
                )
            return {
                "conversation_id": conversation_id,
                "imported": prior is None,
                "message": message,
                "messages": updated.get("messages", []),
                "learner_context": preference,
                **({"context": updated["context"]} if updated.get("context") is not None else {}),
            }
        finally:
            lease.release()

    return routes
