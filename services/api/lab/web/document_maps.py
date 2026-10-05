"""On-demand native document-map endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from lab.document_map_store import (
    build_or_rebuild_document_map,
    get_document_map,
    get_document_map_section,
)
from lab.web.deps import AppDeps
from lab.document_map_summary_store import recover_interrupted_attempts
from lab.errors import Conflict
from lab.web.locks import acquire_topic_lock, topic_lock, topic_lock_busy


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/topics/{topic}/files/{file_id}/map")
    async def read_map(topic: str, file_id: str):
        await _recover_if_idle(deps, topic, file_id)
        return get_document_map(deps.store, topic, file_id)

    @routes.post("/api/topics/{topic}/files/{file_id}/map")
    async def build_map(topic: str, file_id: str):
        async with topic_lock(deps.locks, topic):
            return build_or_rebuild_document_map(deps.store, topic, file_id)

    @routes.get("/api/topics/{topic}/files/{file_id}/map/sections/{section_id}")
    async def read_section(topic: str, file_id: str, section_id: str):
        await _recover_if_idle(deps, topic, file_id)
        return get_document_map_section(deps.store, topic, file_id, section_id)

    return routes


async def _recover_if_idle(deps: AppDeps, topic: str, file_id: str) -> None:
    if topic_lock_busy(deps.locks, topic):
        return
    try:
        lease = await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)
    except Conflict:
        return
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
    finally:
        lease.release()
