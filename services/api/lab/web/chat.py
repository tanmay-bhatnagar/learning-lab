"""Chat and session HTTP routes."""

from __future__ import annotations

import json

from anyio import CancelScope
from fastapi import APIRouter

from lab.chat_prompt import build_chat_prompt
from lab.chat_session import append_assistant_message, append_user_message, history_messages, with_session_context
from lab.errors import Conflict
from lab.retrieval import evidence_messages, search
from lab.storage import read_bytes, read_json
from lab.web.deps import AppDeps
from lab.web.locks import acquire_topic_lock
from lab.web.middleware import FinalizedStreamingResponse
from lab.web.schemas import ChatInput
from lab.web.settings_store import load_settings


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/topics/{topic}/messages")
    def messages(topic: str):
        return deps.store.session(topic)

    @routes.post("/api/topics/{topic}/chat")
    async def chat(topic: str, body: ChatInput):
        lease = await acquire_topic_lock(deps.locks, topic, reject_if_busy=True)
        try:
            session = deps.store.session(topic)
            attachments: list[dict[str, object]] = []
            selected_records = []
            for file_id in dict.fromkeys(body.file_ids):
                record = deps.store.file(topic, file_id)
                if record["status"] != "ready":
                    raise Conflict(f"Attachment {record['name']} is not ready; check its conversion error.")
                selected_records.append(record)
                if record.get("index_status") != "ready":
                    content = read_bytes(deps.store.file_path(topic, record["markdown_name"])).decode("utf-8")
                    attachments.append(
                        {"role": "user", "content": f"UNTRUSTED ATTACHMENT ({record['name']}):\n{content}"}
                    )
            current = load_settings(deps.store)
            indexed_ids = [record["id"] for record in selected_records if record.get("index_status") == "ready"]
            search_result: dict[str, object] = {"hits": [], "mode": "none"}
            path = deps.store.file_path(topic, "retrieval.sqlite")
            if path.exists() and indexed_ids:
                search_fn = deps.retriever or search
                search_result = await search_fn(
                    deps.store,
                    topic,
                    body.message,
                    file_ids=indexed_ids,
                    limit=current.retrieval_top_k,
                    embedding_model=current.embedding_model,
                    embedder=deps.embedder(),
                )
            elif indexed_ids:
                names = ", ".join(
                    record["name"] for record in selected_records if record.get("index_status") == "ready"
                )
                raise Conflict(
                    f"Indexed evidence is unavailable for {names}: the topic retrieval index is missing. "
                    "Restore retrieval.sqlite or re-upload the selected files before chatting.",
                )
            vision = False
            if search_result.get("hits"):
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
            retrieval_record: dict[str, object] = {
                "mode": search_result.get("mode", "none"),
                "warning": search_result.get("warning"),
                "citations": citations,
            }
            topic_metadata = read_json(deps.store.topic(topic) / "topic.json", {})
            plan = build_chat_prompt(
                history=history_messages(session),
                evidence=evidence,
                citations=citations,
                attachments=attachments,
                question=body.message,
                learning_goal=topic_metadata.get("learning_goal", ""),
                context_limit=body.context_limit,
                retrieval_record=retrieval_record,
            )
            session = append_user_message(session, body.message, body.file_ids)
            deps.store.save_session(topic, session)
        except BaseException:
            lease.release()
            raise

        lease.hand_off()
        assistant = {
            "role": "assistant",
            "content": "",
            "thinking": "",
            "model": body.model,
            "retrieval": plan["retrieval_record"],
        }
        complete = False
        finished = False
        stream = None
        prompt = plan["prompt"]
        prompt_context = plan["prompt_context"]
        retrieval_record = plan["retrieval_record"]

        async def finish() -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            with CancelScope(shield=True):
                try:
                    try:
                        if stream is not None and hasattr(stream, "aclose"):
                            await stream.aclose()
                    finally:
                        if not complete:
                            assistant["incomplete"] = True
                            session_updated = append_assistant_message(session, assistant)
                            deps.store.save_session(topic, session_updated)
                finally:
                    lease.release()

        async def events():
            nonlocal complete, stream

            def line(event: dict) -> str:
                return json.dumps(event, ensure_ascii=False) + "\n"

            try:
                stream = deps.model_backend.stream_chat(
                    prompt,
                    body.model,
                    body.think,
                    body.context_limit,
                    context_metadata=prompt_context,
                    generation_lock=deps.model_generation_lock,
                )
                async for event in stream:
                    kind = event.get("type")
                    if kind in {"token", "thinking"}:
                        text = event.get("text", "")
                        assistant["content" if kind == "token" else "thinking"] += text
                        yield line({"type": kind, "text": text})
                    elif kind == "done":
                        assistant["model"] = event.get("model") or body.model
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
                        deps.store.save_session(topic, session_updated)
                        complete = True
                        yield line(event)
                        break
                    elif kind == "error":
                        yield line(event)
                        break
                else:
                    yield line(
                        {
                            "type": "error",
                            "message": "Model stream ended before completion. Partial output was saved; retry when the local model service is ready.",
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - stream must always end with done or error event
                yield line(
                    {
                        "type": "error",
                        "message": f"Chat failed ({type(exc).__name__}). Check the local model service and retry; your message is saved.",
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
