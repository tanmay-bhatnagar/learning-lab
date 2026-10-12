"""HTTP routes for explicit learner-context preferences on an existing conversation."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from lab.learner_context import selected_cv_snapshot
from lab.web.deps import AppDeps
from lab.web.locks import topic_lock
from lab.conversation_profile import get_conversation_profile, save_conversation_profile


class LearnerContextInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    expected_revision: int = Field(ge=0)
    include_cv: bool


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/topics/{topic}/conversations/{conversation_id}/learner-context")
    async def get_learner_context(topic: str, conversation_id: str):
        async with topic_lock(deps.locks, topic, reject_if_busy=True):
            return get_conversation_profile(deps.store, topic, conversation_id)

    @routes.patch("/api/topics/{topic}/conversations/{conversation_id}/learner-context")
    async def update_learner_context(topic: str, conversation_id: str, body: LearnerContextInput):
        async with topic_lock(deps.locks, topic, reject_if_busy=True):
            if body.include_cv:
                selected_cv_snapshot(deps.profile_store)
            return save_conversation_profile(
                deps.store,
                topic,
                conversation_id,
                updates={"include_cv": body.include_cv},
                expected_revision=body.expected_revision,
            )

    return routes
