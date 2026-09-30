"""File upload and artifact HTTP routes."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from typing import Literal

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from lab.errors import InvalidInput, NotFound, TooLarge
from lab.file_records import mark_interrupted
from lab.ingest import error_record, processing_record, ready_from_docling, ready_from_markdown, ready_index_error
from lab.parse_pipeline import parse_and_persist
from lab.retrieval import index_chunks, search
from lab.storage import read_bytes, read_json, write_json, write_new_bytes
from lab.web.deps import AppDeps, ParserFn
from lab.web.locks import topic_lock, topic_lock_busy
from lab.web.schemas import RetrievalInput
from lab.web.settings_store import load_settings


def _default_parser_map() -> dict[str, ParserFn]:
    from lab import parsers

    return {
        "markitdown": lambda data, _parser: parsers.convert_pdf(data, "markitdown"),
        "anydoc": lambda data, _parser: parsers.convert_pdf(data, "anydoc"),
    }


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()
    parser_map = deps.parser_map or _default_parser_map()
    limit = deps.config.max_upload_bytes

    @routes.get("/api/topics/{topic}/files")
    async def files(topic: str):
        records = deps.store.files(topic)
        recovered = mark_interrupted(records, deps.active_uploads)
        if recovered != records and not topic_lock_busy(deps.locks, topic):
            async with topic_lock(deps.locks, topic):
                recovered = mark_interrupted(deps.store.files(topic), deps.active_uploads)
                write_json(deps.store.topic(topic) / "files.json", recovered)
        return {"files": recovered}

    @routes.post("/api/topics/{topic}/files", status_code=201)
    async def upload(
        topic: str,
        file: UploadFile = File(...),
        parser: Literal["docling", "markitdown", "anydoc"] = Form("docling"),
    ):
        file_id = ""
        try:
            async with topic_lock(deps.locks, topic):
                name = file.filename or "document.pdf"
                if "/" in name or "\\" in name or any(ord(c) < 32 for c in name) or not name.lower().endswith(".pdf"):
                    raise InvalidInput("Upload a PDF with a plain filename, without path separators.")
                data = bytearray()
                while chunk := await file.read(65536):
                    data.extend(chunk)
                    if len(data) > limit:
                        raise TooLarge(f"PDF exceeds the {limit} byte upload limit.")
                if not data.startswith(b"%PDF-"):
                    raise InvalidInput("File does not have a valid PDF header.")
                file_id = uuid.uuid4().hex
                deps.active_uploads.add(file_id)
                stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).stem)[:100] or "document"
                original_name = f"{datetime.now(timezone.utc):%Y_%m_%d}_{stem}-{file_id}.pdf"
                record = processing_record(file_id, name, original_name, parser)
                write_new_bytes(deps.store.file_path(topic, original_name), bytes(data))
                records = deps.store.files(topic)
                records.append(record)
                write_json(deps.store.topic(topic) / "files.json", records)
                try:
                    if parser == "docling":
                        parser_fn = deps.structured_parser or parse_and_persist
                        current = load_settings(deps.store)
                        updates, chunks = await run_in_threadpool(
                            parser_fn,
                            deps.store,
                            topic,
                            data=bytes(data),
                            filename=name,
                            original_name=original_name,
                            file_id=file_id,
                            embedding_model=current.embedding_model,
                            artifacts_path=deps.config.docling_artifacts_path,
                            tokenizer_root=deps.config.embedding_tokenizer_root,
                        )
                        record = {**record, **updates}
                        try:
                            index_result = await index_chunks(
                                deps.store,
                                topic,
                                file_id,
                                chunks,
                                embedding_model=current.embedding_model,
                                embedder=deps.embedder(),
                            )
                            record = ready_from_docling(record, updates, index_result)
                        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
                            record = ready_index_error(record, updates, exc)
                    else:
                        convert = parser_map.get(parser)
                        if convert is None:
                            raise ValueError("Choose markitdown or anydoc.")
                        markdown = await run_in_threadpool(convert, bytes(data), parser)
                        if not isinstance(markdown, str) or not markdown.strip():
                            raise ValueError(
                                "No text extracted; scanned PDFs require local OCR before uploading again."
                            )
                        markdown_name = original_name[:-4] + ".md"
                        write_new_bytes(deps.store.file_path(topic, markdown_name), markdown.encode("utf-8"))
                        record = ready_from_markdown(record, markdown_name)
                except Exception as exc:  # noqa: BLE001 - conversion boundary matches original upload outcomes
                    record = error_record(record, exc)
                records[-1] = record
                write_json(deps.store.topic(topic) / "files.json", records)
                return record
        finally:
            deps.active_uploads.discard(file_id)
            await file.close()

    @routes.get("/api/topics/{topic}/files/{file_id}/markdown")
    def markdown(topic: str, file_id: str):
        from lab.errors import Conflict

        record = deps.store.file(topic, file_id)
        if record["status"] != "ready":
            raise Conflict(record.get("error", "Conversion is not complete."))
        return {"markdown": read_bytes(deps.store.file_path(topic, record["markdown_name"])).decode("utf-8")}

    @routes.get("/api/topics/{topic}/files/{file_id}/original")
    def original(topic: str, file_id: str):
        record = deps.store.file(topic, file_id)
        return Response(
            read_bytes(deps.store.file_path(topic, record["original_name"])),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{record["id"]}.pdf"'},
        )

    @routes.get("/api/topics/{topic}/files/{file_id}/parsed")
    def parsed(topic: str, file_id: str):
        from lab.errors import Conflict

        record = deps.store.file(topic, file_id)
        if record.get("status") != "ready" or not record.get("docling_name"):
            raise Conflict("Structured Docling output is not available for this file.")
        return read_json(deps.store.file_path(topic, record["docling_name"]))

    @routes.get("/api/topics/{topic}/files/{file_id}/chunks")
    def chunks(topic: str, file_id: str):
        from lab.errors import Conflict

        record = deps.store.file(topic, file_id)
        if record.get("status") != "ready" or not record.get("chunks_name"):
            raise Conflict("Structured chunks are not available for this file.")
        lines = read_bytes(deps.store.file_path(topic, record["chunks_name"])).decode("utf-8").splitlines()
        return {"chunks": [json.loads(line) for line in lines if line.strip()]}

    @routes.get("/api/topics/{topic}/files/{file_id}/assets/{asset_id}")
    def asset(topic: str, file_id: str, asset_id: str):
        record = deps.store.file(topic, file_id)
        match = next((item for item in record.get("assets", []) if item.get("id") == asset_id), None)
        if not match:
            raise NotFound("Visual asset not found for this file.")
        return Response(
            read_bytes(deps.store.file_path(topic, match["name"])),
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @routes.post("/api/topics/{topic}/retrieval/trace")
    async def retrieval_trace(topic: str, body: RetrievalInput):
        from lab.errors import Conflict

        for file_id in dict.fromkeys(body.file_ids):
            record = deps.store.file(topic, file_id)
            if record.get("index_status") != "ready":
                raise Conflict(f"{record['name']} is not indexed.")
        current = load_settings(deps.store)
        result = await search(
            deps.store,
            topic,
            body.query,
            file_ids=list(dict.fromkeys(body.file_ids)) or None,
            limit=body.top_k,
            embedding_model=current.embedding_model,
            embedder=deps.embedder(),
        )
        return {"query": body.query, **result}

    return routes
