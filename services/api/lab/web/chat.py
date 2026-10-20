"""Chat and session HTTP routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from lab.contracts import Session
from lab.errors import InvalidInput
from lab.query_traces import list_traces, trace_path
from lab.prerequisite_import import validated_prerequisite_imports
from lab.summary_import import validated_summary_imports
from lab.web.deps import AppDeps
from lab.web.locks import acquire_topic_lock, topic_lock
from lab.web.middleware import FinalizedStreamingResponse
from lab.web.schemas import ChatInput
from lab.web.settings_store import load_settings
from lab.workflows.chat import admit_chat, build_chat_graphs, opt_in_evidence
from lab.workflows.chat_stream import build_optin_chat_stream_handle, build_ordinary_chat_stream_handle

logger = logging.getLogger(__name__)


def router(deps: AppDeps) -> APIRouter:
    chat_graphs = build_chat_graphs()
    routes = APIRouter()

    @routes.get("/api/topics/{topic}/messages")
    async def messages(topic: str):
        async with topic_lock(deps.locks, topic):
            session = deps.store.session(topic)
            validated_summary_imports(session, "default")
            validated_prerequisite_imports(session, "default")
            return session

    @routes.get("/api/topics/{topic}/conversations/{conversation_id}/messages")
    async def conversation_messages(topic: str, conversation_id: str):
        async with topic_lock(deps.locks, topic):
            session = deps.store.session(topic, conversation_id)
            validated_summary_imports(session, conversation_id)
            validated_prerequisite_imports(session, conversation_id)
            return session

    @routes.post("/api/topics/{topic}/chat")
    async def chat(topic: str, body: ChatInput):
        return await stream_chat(topic, "default", body)

    @routes.post("/api/topics/{topic}/conversations/{conversation_id}/chat")
    async def conversation_chat(topic: str, conversation_id: str, body: ChatInput):
        return await stream_chat(topic, conversation_id, body)

    @routes.get("/api/topics/{topic}/query-traces")
    async def query_traces(topic: str, conversation_id: str | None = None, limit: int = 100):
        if not 1 <= limit <= 1000:
            raise InvalidInput("limit must be between 1 and 1000.")
        deps.store.topic(topic)
        if conversation_id is not None:
            deps.store.conversation(topic, conversation_id)
        return {
            "traces": list_traces(trace_path(deps.store.topic(topic)), conversation_id=conversation_id, limit=limit)
        }

    async def stream_chat(topic: str, conversation_id: str, body: ChatInput):
        async def acquire_lease():
            return await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)

        admitted = await admit_chat(
            store=deps.store,
            profile_store=deps.profile_store,
            model_backend=deps.model_backend,
            retriever=deps.retriever,
            embedder=deps.embedder(),
            runtime_policy_path=deps.config.runtime_policy_path,
            acquire_lease=acquire_lease,
            load_settings_fn=load_settings,
            topic_id=topic,
            conversation_id=conversation_id,
            message=body.message,
            file_ids=body.file_ids,
            model=body.model,
            think=body.think,
            context_limit=body.context_limit,
            extra_search=body.extra_search,
            admission_graph=chat_graphs.admission,
        )
        lease = admitted.lease

        def save(session: Session) -> None:
            if conversation_id == "default":
                deps.store.save_session(topic, session)
            else:
                deps.store.save_session(topic, session, conversation_id)

        register_run = deps.active_runs.register
        unregister_run = deps.active_runs.unregister
        release_lease = lease.release

        if not body.extra_search:
            handle = build_ordinary_chat_stream_handle(
                admitted=admitted,
                graphs=chat_graphs,
                model_backend=deps.model_backend,
                generation_lock=deps.model_generation_lock,
                save_session=save,
                requested_model=body.model,
                think=body.think,
                context_limit=body.context_limit,
                register_run=register_run,
                unregister_run=unregister_run,
                release_lease=release_lease,
            )
        else:
            handle = build_optin_chat_stream_handle(
                admitted=admitted,
                opt_in=opt_in_evidence(admitted),
                graphs=chat_graphs,
                store=deps.store,
                profile_store=deps.profile_store,
                model_backend=deps.model_backend,
                generation_lock=deps.model_generation_lock,
                retriever=deps.retriever,
                embedder=deps.embedder(),
                runtime_policy_path=deps.config.runtime_policy_path,
                save_session=save,
                requested_model=body.model,
                think=body.think,
                context_limit=body.context_limit,
                file_ids=body.file_ids,
                register_run=register_run,
                unregister_run=unregister_run,
                release_lease=release_lease,
            )

        try:
            return FinalizedStreamingResponse(
                handle.events(),
                on_close=handle.finish,
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
        except BaseException as construction_error:
            try:
                await handle.finish()
            except BaseException as cleanup_error:
                logger.error(
                    "Chat response cleanup failed (%s after %s)",
                    type(cleanup_error).__name__,
                    type(construction_error).__name__,
                )
            raise

    return routes
