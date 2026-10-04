"""Topic conversation catalog routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from lab.web.deps import AppDeps


class ConversationInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/topics/{topic}/conversations")
    def conversations(topic: str):
        return {"conversations": deps.store.conversations(topic)}

    @routes.post("/api/topics/{topic}/conversations")
    def create_conversation(topic: str, body: ConversationInput):
        return deps.store.create_conversation(topic, body.title)

    @routes.patch("/api/topics/{topic}/conversations/{conversation_id}")
    def rename_conversation(topic: str, conversation_id: str, body: ConversationInput):
        return deps.store.rename_conversation(topic, conversation_id, body.title)

    return routes
