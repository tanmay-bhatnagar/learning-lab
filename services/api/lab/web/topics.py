"""Topic HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter

from lab.web.deps import AppDeps
from lab.web.locks import topic_lock
from lab.web.schemas import LearningGoalInput, TopicInput
from lab.storage import read_json, write_json


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/topics")
    def topics():
        return {"topics": deps.store.topics()}

    @routes.post("/api/topics", status_code=201)
    def create_topic(body: TopicInput):
        return deps.store.create(body.name)

    @routes.get("/api/topics/{topic}")
    def get_topic(topic: str):
        return read_json(deps.store.topic(topic) / "topic.json")

    @routes.patch("/api/topics/{topic}")
    @routes.put("/api/topics/{topic}")
    async def rename_topic(topic: str, body: TopicInput):
        async with topic_lock(deps.locks, topic):
            path = deps.store.topic(topic) / "topic.json"
            data = {**read_json(path), "name": body.name}
            write_json(path, data)
            return data

    @routes.put("/api/topics/{topic}/learning-goal")
    async def save_learning_goal(topic: str, body: LearningGoalInput):
        async with topic_lock(deps.locks, topic):
            path = deps.store.topic(topic) / "topic.json"
            data = {**read_json(path), "learning_goal": body.learning_goal}
            write_json(path, data)
            return {"learning_goal": body.learning_goal}

    @routes.delete("/api/topics/{topic}")
    async def archive_topic(topic: str):
        async with topic_lock(deps.locks, topic):
            path = deps.store.topic(topic) / "topic.json"
            data = read_json(path)
            data["archived"] = True
            write_json(path, data)
            return {"id": topic, "archived": True}

    return routes
