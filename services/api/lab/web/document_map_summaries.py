"""Request-bound streaming generation for explicit document-map section summaries."""

from __future__ import annotations

from fastapi import APIRouter

from lab.document_map_summary_store import write_summary_attempt
from lab.web.deps import ActiveSummary, AppDeps
from lab.web.locks import acquire_topic_lock
from lab.web.middleware import FinalizedStreamingResponse
from lab.web.schemas import SectionSummaryInput
from lab.workflows.events import EventSink
from lab.workflows.runtime import PublishOnce
from lab.workflows.summary import (
    SUMMARY_STREAM_EVENT_TYPES,
    SummaryAdmissionContext,
    SummaryExecutionContext,
    build_summary_stream_handle,
    compile_summary_admission_graph,
    compile_summary_execution_graph,
    run_summary_admission,
)
from lab.workflows.summary_publication import SummaryObserver, SummaryPublicationBundle


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()
    summary_admission_graph = compile_summary_admission_graph()
    summary_execution_graph = compile_summary_execution_graph()

    @routes.post("/api/topics/{topic}/files/{file_id}/map/sections/{section_id}/summary")
    async def generate_summary(topic: str, file_id: str, section_id: str, body: SectionSummaryInput):
        lease = await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)

        def list_active_attempt_ids() -> set[str]:
            return {
                attempt_id
                for attempt_id, active in deps.active_document_map_summaries.items()
                if active.topic == topic and active.file_id == file_id
            }

        def register_active(attempt_id: str) -> None:
            deps.active_document_map_summaries[attempt_id] = ActiveSummary(
                topic=topic,
                file_id=file_id,
                revision=body.revision,
                section_id=section_id,
            )

        def unregister_active(attempt_id: str) -> None:
            deps.active_document_map_summaries.pop(attempt_id, None)

        try:
            admission_context = SummaryAdmissionContext(
                store=deps.store,
                runtime_policy_path=deps.config.runtime_policy_path,
                write_attempt=write_summary_attempt,
                topic=topic,
                file_id=file_id,
                section_id=section_id,
                expected_revision=body.revision,
                model=body.model,
                context_limit=body.context_limit,
                think=body.think,
                register_active=register_active,
                list_active_attempt_ids=list_active_attempt_ids,
            )
            admitted = await run_summary_admission(summary_admission_graph, admission_context)
            lease.hand_off()
        except BaseException:
            lease.release()
            raise

        observer = SummaryObserver()
        publish_once: PublishOnce = PublishOnce()
        bundle = SummaryPublicationBundle(
            store=deps.store,
            topic=topic,
            file_id=file_id,
            section_id=section_id,
            expected_revision=body.revision,
            attempt_id=admitted.attempt_id,
            base_attempt=admitted.attempt,
            plan=admitted.plan,
            requested_model=body.model,
            context_limit=body.context_limit,
            think=body.think,
            write_attempt=write_summary_attempt,
        )
        sink = EventSink(allowed_types=SUMMARY_STREAM_EVENT_TYPES)
        execution_context = SummaryExecutionContext(
            model_backend=deps.model_backend,
            generation_lock=deps.model_generation_lock,
            bundle=bundle,
            observer=observer,
            sink=sink,
            publish_once=publish_once,
            plan_messages=admitted.plan["messages"],
            prompt_context=admitted.plan["prompt_context"],
            requested_model=body.model,
            think=body.think,
            context_limit=body.context_limit,
        )

        handle = build_summary_stream_handle(
            admitted=admitted,
            revision=body.revision,
            section_id=section_id,
            execution_graph=summary_execution_graph,
            execution_context=execution_context,
            unregister_active=unregister_active,
            release_lease=lease.release,
            register_run=deps.active_runs.register,
            unregister_run=deps.active_runs.unregister,
        )

        return FinalizedStreamingResponse(
            handle.events(),
            on_close=handle.finish,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return routes
