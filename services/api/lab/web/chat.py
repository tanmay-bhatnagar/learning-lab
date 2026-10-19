"""Chat and session HTTP routes."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from anyio import CancelScope
from fastapi import APIRouter

from lab.chat_prompt import build_chat_prompt
from lab.contracts import Session
from lab.chat_session import append_assistant_message, append_user_message, history_messages, with_session_context
from lab.errors import Conflict, DomainError, InvalidInput
from lab.evidence_prompt import build_final_evidence_prompt, build_initial_evidence_prompt
from lab.evidence_request import MAX_SOURCE_REFERENCES, merge_scoped_sources
from lab.evidence_snapshot import (
    bind_retained_sources,
    capture_prompt_context,
    revalidate_evidence_snapshot,
)
from lab.evidence_turn import EvidenceTurnEvent, run_evidence_turn
from lab.learner_context import load_learner_context
from lab.query_traces import (
    duration,
    finalize as finalize_trace,
    finalize_record,
    insert_started,
    list_traces,
    new_trace_id,
    retrieval_fields,
    started_record,
    trace_path,
)
from lab.retrieval import evidence_messages, search
from lab.runtime_policy import load_runtime_policy
from lab.storage import read_bytes, read_json
from lab.summary_import import validated_summary_imports
from lab.prerequisite_import import validated_prerequisite_imports
from lab.web.deps import AppDeps
from lab.web.locks import acquire_topic_lock, topic_lock
from lab.web.middleware import FinalizedStreamingResponse
from lab.web.schemas import ChatInput
from lab.web.settings_store import load_settings

logger = logging.getLogger(__name__)

_INITIAL_FALLBACK_WARNING = "Selected-document search used bounded opening passages because no query match was found."
_INITIAL_NO_HITS_WARNING = "No indexed passages were returned from the selected documents."
_INITIAL_KEYWORD_WARNING = "Semantic search was unavailable; keyword results were used."


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
        deps.store.topic(topic)
        started = time.monotonic()
        trace_id = new_trace_id()
        record = started_record(
            topic_id=topic,
            conversation_id=conversation_id,
            message_chars=len(body.message),
            model=body.model,
            think=body.think,
            context_limit=body.context_limit,
            embedding_model=None,
            retrieval_top_k=None,
            now=datetime.now(UTC).isoformat(),
            trace_id=trace_id,
        )
        if body.extra_search:
            record["evidence_search"] = _empty_evidence_search()
        record["selected_file_ids"] = list(dict.fromkeys(body.file_ids))
        trace_file = trace_path(deps.store.topic(topic))
        insert_started(trace_file, record)
        trace_state = {"record": record, "done": False}

        def persist_trace(status: str, stage: str, *, error: dict[str, str] | None = None, **updates: object) -> bool:
            if trace_state["done"]:
                return False
            final = finalize_record(
                trace_state["record"],
                status=status,
                now=datetime.now(UTC).isoformat(),
                stage=stage,
                total_ms=(time.monotonic() - started) * 1000,
                error=error,
                **updates,
            )
            try:
                changed = finalize_trace(trace_file, final)
            except Exception as exc:
                logger.error("Query trace finalization failed for %s (%s)", trace_id, type(exc).__name__)
                raise
            if changed:
                trace_state["done"] = True
            return changed

        def save(session: Session) -> None:
            if conversation_id == "default":
                deps.store.save_session(topic, session)
            else:
                deps.store.save_session(topic, session, conversation_id)

        def rejected(exc: BaseException) -> bool:
            return isinstance(exc, DomainError) and exc.status_code < 500

        current = None
        evidence_snapshot = None
        evidence_initial_chunks: tuple[dict[str, object], ...] = ()
        evidence_scope: tuple[str, ...] = ()
        evidence_prompt_kwargs: dict[str, object] | None = None
        evidence_vision = False
        try:
            current = load_settings(deps.store)
            trace_state["record"] = {
                **trace_state["record"],
                "embedding_model": current.embedding_model,
                "retrieval_top_k": current.retrieval_top_k,
            }
            lease = await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)
        except BaseException as exc:
            status = (
                "cancelled"
                if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
                else "rejected"
                if rejected(exc)
                else "error"
            )
            code = "topic_busy" if isinstance(exc, Conflict) else "preflight_failed"
            persist_trace(
                status,
                "preflight",
                error={
                    "stage": "preflight",
                    "code": code,
                    "exception_type": type(exc).__name__,
                    "summary": "Chat could not enter preflight.",
                },
            )
            raise
        try:
            session = deps.store.session(topic, conversation_id)
            validated_summary_imports(session, conversation_id)
            validated_prerequisite_imports(session, conversation_id)
            runtime_policy = None
            learner_context = None
            attachments: list[dict[str, object]] = []
            selected_records = []
            for file_id in dict.fromkeys(body.file_ids):
                record = deps.store.file(topic, file_id)
                if record["status"] != "ready":
                    raise Conflict(f"Attachment {record['name']} is not ready; check its conversion error.")
                selected_records.append(record)
                if record.get("index_status") != "ready" and not body.extra_search:
                    content = read_bytes(deps.store.file_path(topic, record["markdown_name"])).decode("utf-8")
                    attachments.append(
                        {"role": "user", "content": f"UNTRUSTED ATTACHMENT ({record['name']}):\n{content}"}
                    )
            indexed_ids = [record["id"] for record in selected_records if record.get("index_status") == "ready"]
            if body.extra_search:
                if not indexed_ids:
                    raise InvalidInput("Select at least one indexed document to enable additional evidence search.")
                captured = capture_prompt_context(
                    store=deps.store,
                    profile_store=deps.profile_store,
                    topic_id=topic,
                    conversation_id=conversation_id,
                    selected_file_ids=set(body.file_ids),
                    runtime_policy_path=deps.config.runtime_policy_path,
                )
                evidence_snapshot = captured.snapshot
                evidence_scope = tuple(sorted(captured.snapshot.indexed_file_ids))
                context = captured.prompt_context
                runtime_policy = context["runtime_policy"]
                learner_context = {
                    "learner_context": context["learner_context"],
                    "cv_text": context["cv_text"],
                    "cv_name": context["cv_name"],
                }
                attachments = [
                    {
                        "role": "user",
                        "content": f"UNTRUSTED ATTACHMENT ({next(item['name'] for item in context['files'] if item['id'] == file_id)}):\n{content}",
                    }
                    for file_id, content in context["attachments"].items()
                ]
                learning_goal = context["learning_goal"]
            else:
                runtime_policy = load_runtime_policy(deps.config.runtime_policy_path)
                learner_context = load_learner_context(
                    deps.store,
                    deps.profile_store,
                    topic,
                    conversation_id,
                )
                learning_goal = read_json(deps.store.topic(topic) / "topic.json", {}).get("learning_goal", "")
            search_result: dict[str, object] = {"hits": [], "mode": "none"}
            path = deps.store.file_path(topic, "retrieval.sqlite")
            retrieval_started = time.monotonic()
            search_file_ids = list(evidence_scope) if body.extra_search else indexed_ids
            if path.exists() and search_file_ids:
                search_fn = deps.retriever or search
                search_result = await search_fn(
                    deps.store,
                    topic,
                    body.message,
                    file_ids=search_file_ids,
                    limit=current.retrieval_top_k,
                    embedding_model=current.embedding_model,
                    embedder=deps.embedder(),
                )
            elif search_file_ids:
                names = ", ".join(
                    record["name"]
                    for record in (context["files"] if body.extra_search else selected_records)
                    if record.get("index_status") == "ready"
                )
                raise Conflict(
                    f"Indexed evidence is unavailable for {names}: the topic retrieval index is missing. "
                    "Restore retrieval.sqlite or re-upload the selected files before chatting.",
                )
            retrieval_ms = (time.monotonic() - retrieval_started) * 1000
            trace_state["record"] = retrieval_fields(
                trace_state["record"],
                selected_file_ids=list(dict.fromkeys(body.file_ids)),
                search_result=search_result,
                retained_ids=set(),
                citations=[],
                retrieval_ms=retrieval_ms,
            )
            if body.extra_search:
                trace_state["record"]["evidence_search"] = _empty_evidence_search()
            vision = False
            if search_result.get("hits") or body.extra_search:
                try:
                    available = await deps.model_backend.list_models()
                    vision = any(
                        item.get("id") == body.model and item.get("vision") is True
                        for item in available.get("models", [])
                    )
                except Exception:  # noqa: BLE001 - vision is optional; any model-list failure falls back to text evidence
                    vision = False
            evidence, citations = evidence_messages(
                deps.store,
                topic,
                search_result.get("hits", []),
                include_images=vision,
            )
            retrieval_warning = search_result.get("warning")
            if body.extra_search:
                retrieval_warning = (
                    _INITIAL_FALLBACK_WARNING
                    if search_result.get("mode") == "fallback"
                    else _INITIAL_NO_HITS_WARNING
                    if search_result.get("mode") == "none"
                    else _INITIAL_KEYWORD_WARNING
                    if search_result.get("mode") == "keyword" and retrieval_warning
                    else None
                )
            retrieval_record: dict[str, object] = {
                "mode": search_result.get("mode", "none"),
                "warning": retrieval_warning,
                "citations": citations,
            }
            if body.extra_search:
                retrieval_record["evidence_search"] = _empty_evidence_search()
            prompt_kwargs = dict(
                history=history_messages(session),
                evidence=evidence,
                citations=citations,
                attachments=attachments,
                question=body.message,
                active_topic=topic,
                learning_goal=learning_goal,
                runtime_policy=runtime_policy,
                context_limit=body.context_limit,
                retrieval_record=retrieval_record,
                **learner_context,
            )
            if body.extra_search:
                evidence_prompt_kwargs = prompt_kwargs
                plan = build_initial_evidence_prompt(
                    prompt_kwargs=prompt_kwargs,
                    source_chunks=search_result.get("hits", []),
                    selected_file_ids=set(evidence_scope),
                )
                evidence_initial_chunks = tuple(search_result.get("hits", []))
                evidence_metadata = _empty_evidence_search()
                evidence_metadata["initial_available_chunk_ids"] = [
                    str(source["chunk_id"]) for source in evidence_initial_chunks
                ]
                plan["retrieval_record"]["evidence_search"] = evidence_metadata
                retrieval_record["evidence_search"] = evidence_metadata
                trace_state["record"]["evidence_search"] = evidence_metadata
                evidence_vision = vision
            else:
                plan = build_chat_prompt(**prompt_kwargs)
            session = append_user_message(session, body.message, body.file_ids)
            save(session)
            trace_state["record"]["user_saved"] = True
            trace_state["record"]["user_message_index"] = len(session["messages"]) - 1
            elapsed_preflight = (time.monotonic() - started) * 1000
            retained_ids = set() if body.extra_search else {citation["chunk_id"] for citation in plan["citations"]}
            trace_state["record"] = retrieval_fields(
                trace_state["record"],
                selected_file_ids=list(dict.fromkeys(body.file_ids)),
                search_result=search_result,
                retained_ids=retained_ids,
                citations=[] if body.extra_search else citations,
                retrieval_ms=retrieval_ms,
            )
            trace_state["record"]["preflight_ms"] = duration(elapsed_preflight)
            trace_state["record"]["prompt_budget"] = plan["prompt_context"].get("limit")
        except BaseException as exc:
            lease.release()
            status = (
                "cancelled"
                if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
                else "rejected"
                if rejected(exc)
                else "error"
            )
            persist_trace(
                status,
                "preflight",
                error={
                    "stage": "preflight",
                    "code": "preflight_failed",
                    "exception_type": type(exc).__name__,
                    "summary": "Chat preflight did not complete.",
                },
            )
            raise

        lease.hand_off()
        assistant = {
            "role": "assistant",
            "content": "",
            "thinking": "",
            "model": body.model,
            "retrieval": {
                **plan["retrieval_record"],
                **({"citations": []} if body.extra_search else {}),
            },
        }
        complete = False
        finished = False
        trace_finalize_failed = False
        outcome: dict[str, object] = {"status": "cancelled", "stage": "generation", "error": None}
        stream = None
        generation_started = time.monotonic()
        first_output: float | None = None
        prompt = plan["prompt"]
        prompt_context = plan["prompt_context"]
        retrieval_record = dict(assistant["retrieval"])
        evidence_metadata = retrieval_record.get("evidence_search") if body.extra_search else None
        latest_search_result = search_result
        total_retrieval_ms = retrieval_ms

        def update_evidence_metadata(metadata: dict[str, object]) -> None:
            nonlocal evidence_metadata
            evidence_metadata = dict(metadata)
            retrieval_record["evidence_search"] = dict(metadata)
            assistant["retrieval"] = dict(retrieval_record)
            trace_state["record"]["evidence_search"] = dict(metadata)

        def record_initial_supply(metadata: dict[str, object]) -> None:
            supplied_ids = {item for item in metadata.get("initial_chunk_ids", []) if isinstance(item, str)}
            if not supplied_ids:
                return
            initial_citations = [citation for citation in plan["citations"] if citation.get("chunk_id") in supplied_ids]
            retrieval_record["citations"] = initial_citations
            assistant["retrieval"] = dict(retrieval_record)
            trace_state["record"] = retrieval_fields(
                trace_state["record"],
                selected_file_ids=list(dict.fromkeys(body.file_ids)),
                search_result=search_result,
                retained_ids=supplied_ids,
                citations=initial_citations,
                retrieval_ms=total_retrieval_ms,
            )
            trace_state["record"]["evidence_search"] = dict(metadata)

        async def finish() -> None:
            nonlocal finished, trace_finalize_failed
            if finished:
                return
            finished = True
            with CancelScope(shield=True):
                try:
                    save_failure: BaseException | None = None
                    if stream is not None and hasattr(stream, "aclose"):
                        try:
                            await stream.aclose()
                        except BaseException as exc:  # noqa: BLE001 - shielded cleanup must record every close failure
                            outcome.update(
                                status="error",
                                stage="stream_close",
                                error={
                                    "stage": "stream_close",
                                    "code": "stream_close_failed",
                                    "exception_type": type(exc).__name__,
                                    "summary": "Model stream cleanup failed.",
                                },
                            )
                            logger.error("Chat stream cleanup failed for %s (%s)", trace_id, type(exc).__name__)
                    if not complete:
                        if body.extra_search:
                            assert isinstance(evidence_metadata, dict)
                            incomplete_metadata = dict(evidence_metadata)
                            incomplete_metadata["outcome"] = (
                                "cancelled" if outcome["status"] == "cancelled" else "error"
                            )
                            update_evidence_metadata(incomplete_metadata)
                        assistant["incomplete"] = True
                        session_updated = append_assistant_message(session, assistant)
                        try:
                            save(session_updated)
                            trace_state["record"]["assistant_saved"] = True
                            trace_state["record"]["assistant_message_index"] = len(session_updated["messages"]) - 1
                        except Exception as exc:  # noqa: BLE001 - record failed answer persistence before releasing the lease
                            save_failure = exc
                            outcome.update(
                                status="error",
                                stage="assistant_save",
                                error={
                                    "stage": "assistant_save",
                                    "code": "assistant_save_failed",
                                    "exception_type": type(exc).__name__,
                                    "summary": "Assistant response could not be saved.",
                                },
                            )
                            logger.error("Assistant save failed for query %s (%s)", trace_id, type(exc).__name__)
                    if not trace_state["done"] and not trace_finalize_failed:
                        try:
                            persist_trace(
                                outcome["status"],
                                outcome["stage"],
                                error=outcome["error"],
                                output_chars=len(assistant["content"]),
                                thinking_chars=len(assistant["thinking"]),
                                assistant_saved=complete or trace_state["record"].get("assistant_saved", False),
                                assistant_message_index=trace_state["record"].get("assistant_message_index"),
                                generation_ms=duration((time.monotonic() - generation_started) * 1000),
                                first_output_ms=duration((first_output - started) * 1000) if first_output else None,
                            )
                        except Exception as exc:  # noqa: BLE001 - report trace persistence failure and still release the lease
                            trace_finalize_failed = True
                    if save_failure is not None:
                        raise save_failure
                finally:
                    lease.release()

        async def events():
            nonlocal complete, first_output, stream, trace_finalize_failed
            nonlocal prompt, prompt_context, retrieval_record, evidence_snapshot
            nonlocal latest_search_result, total_retrieval_ms

            def line(event: dict) -> str:
                return json.dumps(event, ensure_ascii=False) + "\n"

            try:
                if body.extra_search:
                    assert evidence_snapshot is not None
                    assert evidence_prompt_kwargs is not None

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
                            "evidence_search": dict(evidence_metadata or {}),
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

                    stream = run_evidence_turn(
                        gateway=deps.model_backend,
                        initial_plan=plan,
                        initial_chunks=evidence_initial_chunks,
                        selected_file_ids=evidence_scope,
                        model=body.model,
                        think=body.think,
                        context_limit=body.context_limit,
                        generation_lock=deps.model_generation_lock,
                        lookup=evidence_lookup,
                        build_final=build_final,
                        revalidate=guard_snapshot,
                    )
                else:
                    stream = deps.model_backend.stream_chat(
                        prompt,
                        body.model,
                        body.think,
                        body.context_limit,
                        context_metadata=prompt_context,
                        generation_lock=deps.model_generation_lock,
                    )
                last_evidence_stage = None
                async for event in stream:
                    if body.extra_search:
                        workflow_event: EvidenceTurnEvent = event
                        if workflow_event.kind == "stage":
                            metadata = workflow_event.metadata or {}
                            update_evidence_metadata(metadata)
                            if workflow_event.stage is not None:
                                outcome["stage"] = workflow_event.stage
                            if workflow_event.stage == "deciding" and metadata.get("generation_count", 0) == 1:
                                record_initial_supply(metadata)
                            if workflow_event.stage != last_evidence_stage:
                                last_evidence_stage = workflow_event.stage
                                status_event = {"type": "evidence_status", "stage": workflow_event.stage}
                                warning = metadata.get("warning") or metadata.get("search_warning")
                                if isinstance(warning, str):
                                    status_event["warning"] = warning
                                yield line(status_event)
                            continue
                        if workflow_event.kind == "plan":
                            metadata = workflow_event.metadata or {}
                            update_evidence_metadata(metadata)
                            if workflow_event.plan is None:
                                raise RuntimeError("Evidence workflow omitted its final prompt plan.")
                            final_plan = workflow_event.plan
                            prompt = final_plan["prompt"]
                            prompt_context = final_plan["prompt_context"]
                            retrieval_record = dict(final_plan["retrieval_record"])
                            retrieval_record["evidence_search"] = dict(metadata)
                            assistant["retrieval"] = dict(retrieval_record)
                            combined_hits = merge_scoped_sources(
                                evidence_initial_chunks,
                                latest_search_result.get("hits", []),
                                selected_file_ids=set(evidence_scope),
                                max_sources=MAX_SOURCE_REFERENCES,
                            )
                            trace_state["record"] = retrieval_fields(
                                trace_state["record"],
                                selected_file_ids=list(dict.fromkeys(body.file_ids)),
                                search_result={**latest_search_result, "hits": list(combined_hits)},
                                retained_ids={item["chunk_id"] for item in final_plan["citations"]},
                                citations=final_plan["citations"],
                                retrieval_ms=total_retrieval_ms,
                            )
                            trace_state["record"]["evidence_search"] = dict(metadata)
                            continue
                        if workflow_event.kind == "done":
                            metadata = dict(workflow_event.metadata or {})
                            update_evidence_metadata(metadata)
                            event = {
                                "type": "done",
                                "model": workflow_event.model,
                                "context": workflow_event.context or {},
                            }
                        elif workflow_event.kind == "error":
                            metadata = dict(workflow_event.metadata or {})
                            metadata["outcome"] = "error"
                            update_evidence_metadata(metadata)
                            outcome.update(
                                status="error",
                                stage="generation",
                                error={
                                    "stage": "generation",
                                    "code": workflow_event.error_code or "evidence_failed",
                                    "exception_type": "EvidenceWorkflowError",
                                    "summary": "The additional evidence workflow could not complete.",
                                },
                            )
                            event = {"type": "error", "message": workflow_event.text or "Evidence search failed."}
                        else:
                            event = {"type": workflow_event.kind, "text": workflow_event.text or ""}
                    kind = event.get("type")
                    if kind in {"token", "thinking"}:
                        if first_output is None:
                            first_output = time.monotonic()
                        text = event.get("text", "")
                        assistant["content" if kind == "token" else "thinking"] += text
                        yield line({"type": kind, "text": text})
                    elif kind == "done":
                        actual_model = event.get("model") if isinstance(event.get("model"), str) else None
                        assistant["model"] = actual_model or body.model
                        cleanup_error = None
                        if stream is not None and hasattr(stream, "aclose"):
                            try:
                                await stream.aclose()
                            except Exception as exc:  # noqa: BLE001 - capture provider cleanup without changing a completed answer
                                cleanup_error = {
                                    "stage": "stream_close",
                                    "code": "stream_close_failed",
                                    "exception_type": type(exc).__name__,
                                    "summary": "Model stream cleanup failed.",
                                }
                                logger.error("Chat stream cleanup failed for %s (%s)", trace_id, type(exc).__name__)
                            stream = None
                        merged_context = {
                            **event.get("context", {}),
                            "truncated_messages": prompt_context.get(
                                "truncated_messages",
                                event.get("context", {}).get("truncated_messages", 0),
                            ),
                        }
                        event = {
                            **event,
                            "model": assistant["model"],
                            "retrieval": retrieval_record,
                            "context": merged_context,
                        }
                        session_updated = with_session_context(
                            append_assistant_message(session, assistant),
                            merged_context,
                        )
                        save(session_updated)
                        trace_state["record"]["assistant_saved"] = True
                        trace_state["record"]["assistant_message_index"] = len(session_updated["messages"]) - 1
                        complete = True
                        trace_updates = {
                            "actual_model": actual_model,
                            "context_used": merged_context.get("used"),
                            "cleanup_error": cleanup_error,
                            "final_context": {
                                key: merged_context[key]
                                for key in ("used", "limit", "estimated", "truncated_messages")
                                if key in merged_context
                            },
                            "generation_ms": duration((time.monotonic() - generation_started) * 1000),
                            "first_output_ms": duration((first_output - started) * 1000) if first_output else None,
                            "output_chars": len(assistant["content"]),
                            "thinking_chars": len(assistant["thinking"]),
                        }
                        try:
                            persist_trace("completed", "complete", **trace_updates)
                        except Exception as exc:  # noqa: BLE001 - trace storage failure must be surfaced before done
                            trace_finalize_failed = True
                            logger.error("Query trace finalization failed for %s (%s)", trace_id, type(exc).__name__)
                            yield line(
                                {
                                    "type": "error",
                                    "message": "The answer was saved, but its query trace could not be finalized.",
                                }
                            )
                            outcome.update(status="completed", stage="complete", error=None, **trace_updates)
                            break
                        yield line(event)
                        break
                    elif kind == "error":
                        if not body.extra_search:
                            outcome.update(
                                status="error",
                                stage="generation",
                                error={
                                    "stage": "generation",
                                    "code": "provider_error",
                                    "exception_type": "ProviderError",
                                    "summary": "Model reported a generation error.",
                                },
                            )
                        await finish()
                        yield line(event)
                        if trace_finalize_failed:
                            yield line(
                                {
                                    "type": "error",
                                    "message": "The answer was saved, but its query trace could not be finalized.",
                                }
                            )
                        break
                else:
                    outcome.update(
                        status="error",
                        stage="generation",
                        error={
                            "stage": "generation",
                            "code": "premature_eof",
                            "exception_type": "IncompleteStream",
                            "summary": "Model stream ended before completion.",
                        },
                    )
                    await finish()
                    yield line(
                        {
                            "type": "error",
                            "message": "Model stream ended before completion. Partial output was saved; retry when the local model service is ready.",
                        }
                    )
                    if trace_finalize_failed:
                        yield line(
                            {
                                "type": "error",
                                "message": "The answer was saved, but its query trace could not be finalized.",
                            }
                        )
            except Exception as exc:  # noqa: BLE001 - stream must always end with done or error event
                outcome.update(
                    status="error",
                    stage="generation",
                    error={
                        "stage": "generation",
                        "code": "generation_failed",
                        "exception_type": type(exc).__name__,
                        "summary": "Model generation failed.",
                    },
                )
                await finish()
                yield line(
                    {
                        "type": "error",
                        "message": f"Chat failed ({type(exc).__name__}). Check the local model service and retry; your message is saved.",
                    }
                )
                if trace_finalize_failed:
                    yield line(
                        {
                            "type": "error",
                            "message": "The answer was saved, but its query trace could not be finalized.",
                        }
                    )
            finally:
                await finish()

        return FinalizedStreamingResponse(
            events(),
            on_close=finish,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return routes
