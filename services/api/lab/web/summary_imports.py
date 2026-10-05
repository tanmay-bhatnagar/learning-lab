"""Explicitly copy a completed section-summary snapshot into an existing conversation."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from lab.document_map_store import get_document_map
from lab.errors import Conflict, NotFound
from lab.summary_import import build_summary_import_message, existing_summary_import, find_section_summary
from lab.web.deps import AppDeps
from lab.web.locks import acquire_topic_lock
from lab.web.schemas import SummaryImportInput


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.post("/api/topics/{topic}/conversations/{conversation_id}/summary-imports")
    async def import_summary(topic: str, conversation_id: str, body: SummaryImportInput):
        lease = await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)
        try:
            session = deps.store.session(topic, conversation_id)
            prior = existing_summary_import(
                session,
                conversation_id,
                file_id=body.file_id,
                revision=body.revision,
                section_id=body.section_id,
                summary_id=body.summary_id,
            )
            if prior is not None:
                return {
                    "conversation_id": conversation_id,
                    "imported": False,
                    "message": prior,
                    "messages": session["messages"],
                    **({"context": session["context"]} if session.get("context") is not None else {}),
                }

            response = get_document_map(deps.store, topic, body.file_id)
            if response["status"] != "ready" or response["map"] is None:
                raise Conflict("Rebuild the document map before importing a summary.")
            map_record = response["map"]
            if map_record["revision"] != body.revision:
                raise Conflict("This document map revision is out of date; reload it before importing.")
            summary = find_section_summary(map_record, body.section_id)
            if summary is None or summary.get("id") != body.summary_id or summary.get("revision") != body.revision:
                raise NotFound("Completed saved summary is not present in this section revision.")
            message = build_summary_import_message(
                conversation_id,
                file_id=body.file_id,
                revision=body.revision,
                section_id=body.section_id,
                summary=summary,
                imported_at=datetime.now(UTC).isoformat(),
            )
            updated_session = {**session, "messages": [*session["messages"], message]}
            deps.store.save_session(topic, updated_session, conversation_id)
            return {
                "conversation_id": conversation_id,
                "imported": True,
                "message": message,
                "messages": updated_session["messages"],
                **({"context": updated_session["context"]} if updated_session.get("context") is not None else {}),
            }
        finally:
            lease.release()

    return routes
