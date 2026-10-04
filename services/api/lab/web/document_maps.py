"""On-demand native document-map endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from lab.document_map_store import (
    build_or_rebuild_document_map,
    get_document_map,
    get_document_map_section,
)
from lab.web.deps import AppDeps
from lab.web.locks import topic_lock


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/topics/{topic}/files/{file_id}/map")
    def read_map(topic: str, file_id: str):
        return get_document_map(deps.store, topic, file_id)

    @routes.post("/api/topics/{topic}/files/{file_id}/map")
    async def build_map(topic: str, file_id: str):
        async with topic_lock(deps.locks, topic):
            return build_or_rebuild_document_map(deps.store, topic, file_id)

    @routes.get("/api/topics/{topic}/files/{file_id}/map/sections/{section_id}")
    def read_section(topic: str, file_id: str, section_id: str):
        return get_document_map_section(deps.store, topic, file_id, section_id)

    return routes
