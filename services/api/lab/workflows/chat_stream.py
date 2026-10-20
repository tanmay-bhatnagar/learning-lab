"""Chat execution GraphRun stream handle (ordinary and opt-in)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from anyio import CancelScope
from langgraph.graph.state import CompiledStateGraph

from lab.contracts import ModelGateway, Session, StoreProtocol
from lab.evidence_prompt import EvidencePromptPlan
from lab.profile_store import ProfileStore
from lab.workflows.chat import (
    CHAT_QUEUED_EVENT_TYPES,
    EXECUTION_RECURSION_LIMIT,
    AdmittedChat,
    AdmittedOptInEvidence,
    ChatExecutionContext,
    ChatGraphs,
    EmbedderFn,
    RetrieverFn,
)
from lab.workflows.chat_evidence import OPTIN_EXECUTION_RECURSION_LIMIT, ChatOptInExecutionContext
from lab.workflows.chat_publication import (
    ChatObserver,
    ChatOptInObserver,
    ChatOptInPublicationBundle,
    ChatPublicationBundle,
    ChatPublicationOutcome,
    apply_optin_pre_commit_disconnect,
    commit_optin_publication,
    commit_ordinary_publication,
    emit_late_graph_failure,
)
from lab.workflows.events import EventSink
from lab.workflows.runtime import GraphRun, PublishOnce

logger = logging.getLogger(__name__)

CommitPublicationFn = Callable[..., Awaitable[ChatPublicationOutcome]]
RegisterRunFn = Callable[[GraphRun], None]
BeforeCommitFn = Callable[[bool], None]
MarkFailureFn = Callable[[BaseException], None]

ChatExecutionContextUnion = ChatExecutionContext | ChatOptInExecutionContext


async def _yield_prepared_terminals(
    *,
    publish_latch: PublishOnce,
    prepared: ChatPublicationOutcome | None,
    commit: CommitPublicationFn,
    bundle: ChatPublicationBundle | ChatOptInPublicationBundle,
    observer: ChatObserver | ChatOptInObserver,
    delivered_complete: list[bool],
    outcome_box: list[ChatPublicationOutcome | None],
) -> AsyncIterator[dict[str, object]]:
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


@dataclass
class ChatStreamHandle:
    """GraphRun-backed NDJSON stream with shielded finish and single publication latch."""

    run: GraphRun
    publish_latch: PublishOnce
    execution_context: ChatExecutionContextUnion
    commit: CommitPublicationFn
    bundle: ChatPublicationBundle | ChatOptInPublicationBundle
    observer: ChatObserver | ChatOptInObserver
    trace_id: str
    register_run: RegisterRunFn
    unregister_run: RegisterRunFn
    release_lease: Callable[[], None]
    before_commit: BeforeCommitFn | None
    mark_failure: MarkFailureFn
    delivered_complete: list[bool] = field(default_factory=lambda: [False])
    _finished: bool = False

    async def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        with CancelScope(shield=True):
            try:
                await self.run.cancel_and_wait()
                provider_stream = self.execution_context.provider_stream
                if provider_stream is not None:
                    try:
                        await provider_stream.aclose()
                    except Exception as exc:  # noqa: BLE001 - shielded cleanup must not block lease release
                        logger.error(
                            "Chat stream cleanup failed for %s (%s)",
                            self.trace_id,
                            type(exc).__name__,
                        )
                if self.before_commit is not None:
                    self.before_commit(self.delivered_complete[0])
                publication_outcome = await self.publish_latch.run(
                    lambda: self.commit(
                        self.bundle,
                        self.observer,
                        prepared=self.execution_context.publication_outcome,
                        terminal_delivered=self.delivered_complete[0],
                    )
                )
                self.execution_context.publication_outcome = publication_outcome
                if publication_outcome.save_failure is not None:
                    raise publication_outcome.save_failure
            finally:
                self.unregister_run(self.run)
                self.release_lease()

    async def events(self) -> AsyncIterator[str]:
        def line(event: Mapping[str, object]) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        try:
            self.register_run(self.run)
            async for event in self.run.events():
                yield line(dict(event))
        finally:
            await self.finish()


def build_chat_stream_handle(
    *,
    graph: CompiledStateGraph[Any, Any, Any, Any],
    recursion_limit: int,
    execution_context: ChatExecutionContextUnion,
    sink: EventSink,
    publish_latch: PublishOnce,
    commit: CommitPublicationFn,
    bundle: ChatPublicationBundle | ChatOptInPublicationBundle,
    observer: ChatObserver | ChatOptInObserver,
    trace_id: str,
    register_run: RegisterRunFn,
    unregister_run: RegisterRunFn,
    release_lease: Callable[[], None],
    before_commit: BeforeCommitFn | None,
    mark_failure: MarkFailureFn,
) -> ChatStreamHandle:
    delivered_complete: list[bool] = [False]

    async def terminal_events(
        _graph_outcome: dict[str, object] | None,
        error: BaseException | None,
    ) -> AsyncIterator[dict[str, object]]:
        if error is not None:
            if isinstance(error, asyncio.CancelledError):
                observer.mark_cancelled()
            else:
                mark_failure(error)
        prepared = execution_context.publication_outcome
        outcome_box: list[ChatPublicationOutcome | None] = [prepared]
        async for event in _yield_prepared_terminals(
            publish_latch=publish_latch,
            prepared=prepared,
            commit=commit,
            bundle=bundle,
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

    run = GraphRun(
        graph=graph,
        state={},
        context=execution_context,
        recursion_limit=recursion_limit,
        sink=sink,
        terminal_events=terminal_events,
    )
    return ChatStreamHandle(
        run=run,
        publish_latch=publish_latch,
        execution_context=execution_context,
        commit=commit,
        bundle=bundle,
        observer=observer,
        trace_id=trace_id,
        register_run=register_run,
        unregister_run=unregister_run,
        release_lease=release_lease,
        before_commit=before_commit,
        mark_failure=mark_failure,
        delivered_complete=delivered_complete,
    )


def _ordinary_mark_failure(observer: ChatObserver) -> MarkFailureFn:
    def mark(error: BaseException) -> None:
        observer.mark_generation_failed(error)

    return mark


def _optin_before_commit(
    bundle: ChatOptInPublicationBundle,
    observer: ChatOptInObserver,
    execution_context: ChatOptInExecutionContext,
) -> BeforeCommitFn:
    def before(terminal_delivered: bool) -> None:
        apply_optin_pre_commit_disconnect(
            bundle,
            observer,
            execution_context.evidence_state,
            assistant_saved=bool(bundle.trace.record.get("assistant_saved")),
            terminal_delivered=terminal_delivered,
        )

    return before


def _optin_mark_failure(observer: ChatOptInObserver) -> MarkFailureFn:
    def mark(error: BaseException) -> None:
        observer.set_workflow_error("generation_failed", str(error))

    return mark


def build_ordinary_chat_stream_handle(
    *,
    admitted: AdmittedChat,
    graphs: ChatGraphs,
    model_backend: ModelGateway,
    generation_lock: asyncio.Lock,
    save_session: Callable[[Session], None],
    requested_model: str,
    think: bool | str | None,
    context_limit: int,
    register_run: RegisterRunFn,
    unregister_run: RegisterRunFn,
    release_lease: Callable[[], None],
) -> ChatStreamHandle:
    plan = admitted.plan
    generation_started = time.monotonic()
    observer = ChatObserver(
        generation_started=generation_started,
        started_monotonic=admitted.started_monotonic,
    )
    publish_latch = PublishOnce()
    publication_bundle = ChatPublicationBundle(
        session=admitted.session,
        plan=plan,
        trace=admitted.trace,
        save_session=save_session,
        requested_model=requested_model,
        prompt_context=plan["prompt_context"],
        retrieval_record=dict(plan["retrieval_record"]),
        trace_id=admitted.trace.trace_id,
    )
    sink = EventSink(allowed_types=CHAT_QUEUED_EVENT_TYPES, capacity=1)
    execution_context = ChatExecutionContext(
        model_backend=model_backend,
        generation_lock=generation_lock,
        sink=sink,
        observer=observer,
        bundle=publication_bundle,
        prompt=plan["prompt"],
        model=requested_model,
        think=think,
        context_limit=context_limit,
    )
    return build_chat_stream_handle(
        graph=graphs.execution,
        recursion_limit=EXECUTION_RECURSION_LIMIT,
        execution_context=execution_context,
        sink=sink,
        publish_latch=publish_latch,
        commit=commit_ordinary_publication,
        bundle=publication_bundle,
        observer=observer,
        trace_id=admitted.trace.trace_id,
        register_run=register_run,
        unregister_run=unregister_run,
        release_lease=release_lease,
        before_commit=None,
        mark_failure=_ordinary_mark_failure(observer),
    )


def build_optin_chat_stream_handle(
    *,
    admitted: AdmittedChat,
    opt_in: AdmittedOptInEvidence,
    graphs: ChatGraphs,
    store: StoreProtocol,
    profile_store: ProfileStore,
    model_backend: ModelGateway,
    generation_lock: asyncio.Lock,
    retriever: RetrieverFn | None,
    embedder: EmbedderFn,
    runtime_policy_path: Path,
    save_session: Callable[[Session], None],
    requested_model: str,
    think: bool | str | None,
    context_limit: int,
    file_ids: list[str],
    register_run: RegisterRunFn,
    unregister_run: RegisterRunFn,
    release_lease: Callable[[], None],
) -> ChatStreamHandle:
    plan = cast(EvidencePromptPlan, admitted.plan)
    generation_started = time.monotonic()
    latest_search_result = admitted.search_result
    total_retrieval_ms = admitted.retrieval_ms
    observer = ChatOptInObserver(
        generation_started=generation_started,
        started_monotonic=admitted.started_monotonic,
    )
    publish_latch = PublishOnce()
    retrieval_record = {**plan["retrieval_record"], "citations": []}
    publication_bundle = ChatOptInPublicationBundle(
        session=admitted.session,
        initial_plan=plan,
        trace=admitted.trace,
        save_session=save_session,
        requested_model=requested_model,
        retrieval_record=retrieval_record,
        trace_id=admitted.trace.trace_id,
        file_ids=file_ids,
        search_result=admitted.search_result,
        total_retrieval_ms=total_retrieval_ms,
        generation_started=generation_started,
        started_monotonic=admitted.started_monotonic,
        initial_chunks=opt_in.initial_chunks,
        evidence_scope=opt_in.scope,
    )
    sink = EventSink(allowed_types=CHAT_QUEUED_EVENT_TYPES, capacity=1)
    execution_context = ChatOptInExecutionContext(
        model_backend=model_backend,
        generation_lock=generation_lock,
        sink=sink,
        bundle=publication_bundle,
        initial_plan=plan,
        initial_chunks=opt_in.initial_chunks,
        evidence_scope=opt_in.scope,
        model=requested_model,
        think=think,
        context_limit=context_limit,
        store=store,
        profile_store=profile_store,
        topic_id=admitted.topic_id,
        retriever=retriever,
        embedder=embedder,
        runtime_policy_path=runtime_policy_path,
        retrieval_top_k=admitted.current_settings.retrieval_top_k,
        embedding_model=admitted.current_settings.embedding_model,
        evidence_vision=opt_in.vision,
        evidence_prompt_kwargs=opt_in.prompt_kwargs,
        evidence_snapshot=opt_in.snapshot,
        observer=observer,
        file_ids=file_ids,
        latest_search_result=latest_search_result,
        total_retrieval_ms=total_retrieval_ms,
    )
    return build_chat_stream_handle(
        graph=graphs.optin_execution,
        recursion_limit=OPTIN_EXECUTION_RECURSION_LIMIT,
        execution_context=execution_context,
        sink=sink,
        publish_latch=publish_latch,
        commit=commit_optin_publication,
        bundle=publication_bundle,
        observer=observer,
        trace_id=admitted.trace.trace_id,
        register_run=register_run,
        unregister_run=unregister_run,
        release_lease=release_lease,
        before_commit=_optin_before_commit(publication_bundle, observer, execution_context),
        mark_failure=_optin_mark_failure(observer),
    )
