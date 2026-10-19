"""Chat and session HTTP routes."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from anyio import CancelScope
from fastapi import APIRouter

from lab.contracts import Session
from lab.errors import InvalidInput
from lab.evidence_prompt import build_final_evidence_prompt
from lab.evidence_request import MAX_SOURCE_REFERENCES, merge_scoped_sources
from lab.evidence_snapshot import bind_retained_sources, revalidate_evidence_snapshot
from lab.query_traces import list_traces, trace_path
from lab.prerequisite_import import validated_prerequisite_imports
from lab.retrieval import evidence_messages, search
from lab.summary_import import validated_summary_imports
from lab.web.deps import AppDeps
from lab.web.locks import acquire_topic_lock, topic_lock
from lab.web.middleware import FinalizedStreamingResponse
from lab.web.schemas import ChatInput
from lab.web.settings_store import load_settings
from lab.workflows.chat import (
    CHAT_QUEUED_EVENT_TYPES,
    EXECUTION_RECURSION_LIMIT,
    ChatExecutionContext,
    admit_chat,
    build_chat_graphs,
)
from lab.workflows.chat_evidence import OPTIN_EXECUTION_RECURSION_LIMIT, ChatOptInExecutionContext
from lab.workflows.chat_publication import (
    ChatObserver,
    ChatOptInObserver,
    ChatOptInPublicationBundle,
    ChatPublicationBundle,
    ChatPublicationOutcome,
    commit_optin_publication,
    commit_ordinary_publication,
    emit_late_graph_failure,
)
from lab.workflows.events import EventSink
from lab.workflows.runtime import GraphRun, PublishOnce

logger = logging.getLogger(__name__)

_INITIAL_FALLBACK_WARNING = "Selected-document search used bounded opening passages because no query match was found."
_INITIAL_NO_HITS_WARNING = "No indexed passages were returned from the selected documents."
_INITIAL_KEYWORD_WARNING = "Semantic search was unavailable; keyword results were used."


CommitFn = Callable[..., Awaitable[ChatPublicationOutcome]]


async def _yield_prepared_terminals(
    *,
    publish_latch: PublishOnce,
    prepared: ChatPublicationOutcome | None,
    commit: CommitFn,
    bundle: ChatPublicationBundle | ChatOptInPublicationBundle,
    observer: ChatObserver | ChatOptInObserver,
    delivered_complete: list[bool],
    outcome_box: list[ChatPublicationOutcome | None],
) -> AsyncIterator[dict[str, object]]:
    """Commit through the request latch once, then yield prepared terminal events."""
    if prepared is not None and prepared.terminal_events:
        terminal_delivered = any(event.get("type") == "done" for event in prepared.terminal_events)
        if terminal_delivered:
            delivered_complete[0] = True
        outcome_box[0] = await publish_latch.run(
            lambda td=terminal_delivered: commit(bundle, observer, prepared=prepared, terminal_delivered=td)
        )
        for event in outcome_box[0].terminal_events:
            yield dict(event)
        return
    outcome_box[0] = await publish_latch.run(
        lambda: commit(bundle, observer, prepared=prepared, terminal_delivered=False)
    )
    for event in outcome_box[0].terminal_events:
        yield dict(event)


def _empty_evidence_search() -> dict[str, object]:
    return {
        "schema_version": 1,
        "requested": True,
        "action": None,
        "outcome": "in_progress",
        "generation_count": 0,
        "lookup_count": 0,
        "initial_available_chunk_ids": [],
        "initial_chunk_ids": [],
        "returned_chunk_ids": [],
        "new_chunk_ids": [],
        "retained_new_chunk_ids": [],
        "final_chunk_ids": [],
        "declared_source_labels": [],
        "search_mode": None,
        "search_warning": None,
        "warning": None,
    }


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
            from lab.errors import InvalidInput

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
        session = admitted.session
        plan = admitted.plan
        search_result = admitted.search_result
        retrieval_ms = admitted.retrieval_ms
        current = admitted.current_settings
        trace = admitted.trace
        started = admitted.started_monotonic
        trace_id = trace.trace_id
        evidence_snapshot = admitted.evidence_snapshot
        evidence_initial_chunks = admitted.evidence_initial_chunks
        evidence_scope = admitted.evidence_scope
        evidence_prompt_kwargs = admitted.evidence_prompt_kwargs
        evidence_vision = admitted.evidence_vision

        def persist_trace(status: str, stage: str, *, error: dict[str, str] | None = None, **updates: object) -> bool:
            return trace.persist(status, stage, error=error, **updates)

        def save(session: Session) -> None:
            if conversation_id == "default":
                deps.store.save_session(topic, session)
            else:
                deps.store.save_session(topic, session, conversation_id)

        if not body.extra_search:
            generation_started = time.monotonic()
            observer = ChatObserver(
                generation_started=generation_started,
                started_monotonic=started,
            )
            publish_latch: PublishOnce = PublishOnce()
            publication_bundle = ChatPublicationBundle(
                session=session,
                plan=plan,
                trace=trace,
                save_session=save,
                requested_model=body.model,
                prompt_context=plan["prompt_context"],
                retrieval_record=dict(plan["retrieval_record"]),
                trace_id=trace_id,
            )
            # Capacity 1 couples provider progress to ASGI consumption (disconnect mid-stream).
            sink = EventSink(allowed_types=CHAT_QUEUED_EVENT_TYPES, capacity=1)
            execution_context = ChatExecutionContext(
                model_backend=deps.model_backend,
                generation_lock=deps.model_generation_lock,
                sink=sink,
                observer=observer,
                bundle=publication_bundle,
                prompt=plan["prompt"],
                model=body.model,
                think=body.think,
                context_limit=body.context_limit,
            )

            delivered_complete = [False]

            async def terminal_events(
                _graph_outcome: dict[str, object] | None,
                error: BaseException | None,
            ):
                if error is not None:
                    if isinstance(error, asyncio.CancelledError):
                        observer.mark_cancelled()
                    else:
                        observer.mark_generation_failed(error)
                prepared = execution_context.publication_outcome
                outcome_box: list[ChatPublicationOutcome | None] = [prepared]
                async for event in _yield_prepared_terminals(
                    publish_latch=publish_latch,
                    prepared=prepared,
                    commit=commit_ordinary_publication,
                    bundle=publication_bundle,
                    observer=observer,
                    delivered_complete=delivered_complete,
                    outcome_box=outcome_box,
                ):
                    yield event
                if outcome_box[0] is not None:
                    execution_context.publication_outcome = outcome_box[0]
                publication = execution_context.publication_outcome
                if error is not None and publication is not None and publication.complete and publication.published:
                    async for item in emit_late_graph_failure(publication=publication, graph_error=error):
                        yield item

            graph_run = GraphRun(
                graph=chat_graphs.execution,
                state={},
                context=execution_context,
                recursion_limit=EXECUTION_RECURSION_LIMIT,
                sink=sink,
                terminal_events=terminal_events,
            )
            finished = False

            async def finish() -> None:
                nonlocal finished
                if finished:
                    return
                finished = True
                with CancelScope(shield=True):
                    try:
                        await graph_run.cancel_and_wait()
                        if execution_context.provider_stream is not None and hasattr(
                            execution_context.provider_stream,
                            "aclose",
                        ):
                            try:
                                await execution_context.provider_stream.aclose()
                            except Exception as exc:  # noqa: BLE001 - shielded cleanup must not block lease release
                                logger.error(
                                    "Chat stream cleanup failed for %s (%s)",
                                    trace_id,
                                    type(exc).__name__,
                                )
                        publication_outcome = await publish_latch.run(
                            lambda: commit_ordinary_publication(
                                publication_bundle,
                                observer,
                                prepared=execution_context.publication_outcome,
                                terminal_delivered=delivered_complete[0],
                            )
                        )
                        execution_context.publication_outcome = publication_outcome
                        if publication_outcome.save_failure is not None:
                            raise publication_outcome.save_failure
                    finally:
                        deps.active_runs.unregister(graph_run)
                        lease.release()

            async def ordinary_events():
                def line(event: dict) -> str:
                    return json.dumps(event, ensure_ascii=False) + "\n"

                try:
                    deps.active_runs.register(graph_run)
                    async for event in graph_run.events():
                        yield line(dict(event))
                finally:
                    await finish()

            return FinalizedStreamingResponse(
                ordinary_events(),
                on_close=finish,
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )

        assert evidence_snapshot is not None
        assert evidence_prompt_kwargs is not None
        generation_started = time.monotonic()
        latest_search_result = search_result
        total_retrieval_ms = retrieval_ms

        async def evidence_lookup(query: str, *, file_ids: tuple[str, ...]) -> dict[str, object]:
            nonlocal latest_search_result, total_retrieval_ms
            if file_ids != evidence_scope:
                raise InvalidInput("Additional search scope no longer matches the captured selection.")
            lookup_started = time.monotonic()
            search_fn = deps.retriever or search
            latest_search_result = await search_fn(
                deps.store,
                topic,
                query,
                file_ids=list(evidence_scope),
                limit=current.retrieval_top_k,
                embedding_model=current.embedding_model,
                embedder=deps.embedder(),
            )
            total_retrieval_ms += (time.monotonic() - lookup_started) * 1000
            return latest_search_result

        def build_final(
            initial_hits: Sequence[Mapping[str, object]],
            additional_hits: Sequence[Mapping[str, object]],
        ):
            combined_hits = merge_scoped_sources(
                initial_hits,
                additional_hits,
                selected_file_ids=set(evidence_scope),
                max_sources=MAX_SOURCE_REFERENCES,
            )
            final_evidence, final_citations = evidence_messages(
                deps.store,
                topic,
                combined_hits,
                include_images=evidence_vision,
            )
            mode = latest_search_result.get("mode", "none")
            final_warning = (
                _INITIAL_FALLBACK_WARNING
                if mode == "fallback"
                else _INITIAL_NO_HITS_WARNING
                if mode == "none"
                else _INITIAL_KEYWORD_WARNING
                if mode == "keyword" and latest_search_result.get("warning")
                else None
            )
            final_retrieval_record = {
                "mode": mode,
                "warning": final_warning,
                "citations": final_citations,
                "evidence_search": dict(
                    publication_bundle.trace.record.get("evidence_search")
                    or plan["retrieval_record"].get("evidence_search")
                    or _empty_evidence_search()
                ),
            }
            final_kwargs = {
                **evidence_prompt_kwargs,
                "evidence": final_evidence,
                "citations": final_citations,
                "retrieval_record": final_retrieval_record,
            }
            return build_final_evidence_prompt(
                prompt_kwargs=final_kwargs,
                initial_chunks=initial_hits,
                additional_chunks=additional_hits,
                selected_file_ids=set(evidence_scope),
                max_sources=current.retrieval_top_k,
            )

        def guard_snapshot(
            sources: Sequence[Mapping[str, object]],
            *,
            supplied_images: Sequence[object],
        ) -> None:
            nonlocal evidence_snapshot
            candidate = bind_retained_sources(
                evidence_snapshot,
                sources,
                supplied_images=supplied_images,
            )
            revalidate_evidence_snapshot(
                candidate,
                store=deps.store,
                profile_store=deps.profile_store,
                runtime_policy_path=deps.config.runtime_policy_path,
            )
            evidence_snapshot = candidate

        observer = ChatOptInObserver(
            generation_started=generation_started,
            started_monotonic=started,
        )
        publish_latch = PublishOnce()
        retrieval_record = {**plan["retrieval_record"], "citations": []}
        publication_bundle = ChatOptInPublicationBundle(
            session=session,
            initial_plan=plan,
            trace=trace,
            save_session=save,
            requested_model=body.model,
            retrieval_record=retrieval_record,
            trace_id=trace_id,
            file_ids=body.file_ids,
            search_result=search_result,
            total_retrieval_ms=total_retrieval_ms,
            generation_started=generation_started,
            started_monotonic=started,
            initial_chunks=evidence_initial_chunks,
            evidence_scope=evidence_scope,
        )
        sink = EventSink(allowed_types=CHAT_QUEUED_EVENT_TYPES, capacity=1)
        execution_context = ChatOptInExecutionContext(
            model_backend=deps.model_backend,
            generation_lock=deps.model_generation_lock,
            sink=sink,
            bundle=publication_bundle,
            initial_plan=plan,
            initial_chunks=evidence_initial_chunks,
            evidence_scope=evidence_scope,
            model=body.model,
            think=body.think,
            context_limit=body.context_limit,
            lookup=evidence_lookup,
            build_final=build_final,
            revalidate=guard_snapshot,
            observer=observer,
            file_ids=body.file_ids,
            latest_search_result=latest_search_result,
            total_retrieval_ms=total_retrieval_ms,
        )

        delivered_complete = [False]

        async def terminal_events(
            _graph_outcome: dict[str, object] | None,
            error: BaseException | None,
        ):
            if error is not None:
                if isinstance(error, asyncio.CancelledError):
                    observer.mark_cancelled()
                else:
                    observer.set_workflow_error("generation_failed", str(error))
            prepared = execution_context.publication_outcome
            outcome_box: list[ChatPublicationOutcome | None] = [prepared]
            async for event in _yield_prepared_terminals(
                publish_latch=publish_latch,
                prepared=prepared,
                commit=commit_optin_publication,
                bundle=publication_bundle,
                observer=observer,
                delivered_complete=delivered_complete,
                outcome_box=outcome_box,
            ):
                yield event
            if outcome_box[0] is not None:
                execution_context.publication_outcome = outcome_box[0]
            publication = execution_context.publication_outcome
            if error is not None and publication is not None and publication.complete and publication.published:
                async for item in emit_late_graph_failure(publication=publication, graph_error=error):
                    yield item

        graph_run = GraphRun(
            graph=chat_graphs.optin_execution,
            state={},
            context=execution_context,
            recursion_limit=OPTIN_EXECUTION_RECURSION_LIMIT,
            sink=sink,
            terminal_events=terminal_events,
        )
        finished = False

        async def finish() -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            with CancelScope(shield=True):
                try:
                    await graph_run.cancel_and_wait()
                    if execution_context.provider_stream is not None and hasattr(
                        execution_context.provider_stream,
                        "aclose",
                    ):
                        try:
                            await execution_context.provider_stream.aclose()
                        except Exception as exc:  # noqa: BLE001 - shielded cleanup must not block lease release
                            logger.error(
                                "Chat stream cleanup failed for %s (%s)",
                                trace_id,
                                type(exc).__name__,
                            )
                    if not trace.record.get("assistant_saved") and not delivered_complete[0]:
                        observer.mark_cancelled()
                        if isinstance(execution_context.evidence_state.get("outcome"), str):
                            execution_context.evidence_state["outcome"] = "cancelled"
                        publication_bundle.trace.record["evidence_search"] = dict(execution_context.evidence_state)
                    publication_outcome = await publish_latch.run(
                        lambda: commit_optin_publication(
                            publication_bundle,
                            observer,
                            prepared=execution_context.publication_outcome,
                            terminal_delivered=delivered_complete[0],
                        )
                    )
                    execution_context.publication_outcome = publication_outcome
                    if publication_outcome.save_failure is not None:
                        raise publication_outcome.save_failure
                finally:
                    deps.active_runs.unregister(graph_run)
                    lease.release()

        async def optin_events():
            def line(event: dict) -> str:
                return json.dumps(event, ensure_ascii=False) + "\n"

            try:
                deps.active_runs.register(graph_run)
                async for event in graph_run.events():
                    yield line(dict(event))
            finally:
                await finish()

        return FinalizedStreamingResponse(
            optin_events(),
            on_close=finish,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return routes
