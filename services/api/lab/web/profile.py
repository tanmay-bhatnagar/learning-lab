"""Reusable CV profile routes and independent My proficiency persistence."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from lab.errors import Conflict, InvalidInput, TooLarge
from lab.learner_profile import validate_cv_filename
from lab.web.deps import AppDeps


class ProfileRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


class ProficiencyCreateInput(ProfileRevisionInput):
    concept: str
    comfort: Literal["comfortable", "refresher", "new", "unsure"]
    notes: str = ""


class ProficiencyUpdateInput(ProfileRevisionInput):
    concept: str | None = None
    comfort: Literal["comfortable", "refresher", "new", "unsure"] | None = None
    notes: str | None = None


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()
    limit = deps.config.max_upload_bytes

    @routes.get("/api/profile")
    def get_profile():
        return deps.profile_store.read_profile()

    @routes.post("/api/profile/cvs", status_code=201)
    async def upload_cv(
        file: UploadFile = File(...),
        original_name: str | None = Form(None),
        parser: Literal["docling", "markitdown", "anydoc"] = Form("docling"),
    ):
        name = original_name if original_name is not None else file.filename
        if not isinstance(name, str):
            raise InvalidInput("Choose a filename for the CV before uploading it.")
        name = validate_cv_filename(name)
        if not name.lower().endswith(".pdf"):
            raise InvalidInput("Upload the CV as a PDF file.")
        if parser not in {"docling", "markitdown", "anydoc"}:
            raise InvalidInput("Choose a supported PDF parser.")
        data = bytearray()
        try:
            while chunk := await file.read(65536):
                data.extend(chunk)
                if len(data) > limit:
                    raise TooLarge(f"CV exceeds the {limit} byte upload limit.")
            if not data.startswith(b"%PDF-"):
                raise InvalidInput("File does not have a valid PDF header.")
            raw = bytes(data)
            await run_in_threadpool(deps.profile_store.check_filename_available, name)
            try:
                parsed = await run_in_threadpool(deps.profile_parser, raw, name, parser)
                canonical_text, native_document, parser_version, diagnostics = _validated_parse(parsed, parser)
            except Exception as exc:  # noqa: BLE001 - persist the original as an ineligible CV record
                canonical_text = ""
                native_document = None
                parser_version = "unknown"
                diagnostics = {"status": "error", "findings": [f"CV conversion failed ({type(exc).__name__})."]}
            record = await run_in_threadpool(
                deps.profile_store.register_cv,
                name,
                raw,
                canonical_text,
                diagnostics,
                parser=parser,
                parser_version=parser_version,
                native_document=native_document,
            )
            profile_data = await run_in_threadpool(deps.profile_store.read_profile)
            return {**record, "revision": profile_data["revision"]}
        finally:
            await file.close()

    @routes.get("/api/profile/cvs/{cv_id}/text")
    def cv_text(cv_id: str):
        record = _cv_record(deps, cv_id)
        text = deps.profile_store.read_extracted_text(cv_id)
        return {
            "id": cv_id,
            "original_name": record["original_name"],
            "parser": record["parser"],
            "parser_version": record["parser_version"],
            "text": text,
        }

    @routes.get("/api/profile/cvs/{cv_id}/original")
    def cv_original(cv_id: str):
        _cv_record(deps, cv_id)
        return Response(
            deps.profile_store.read_original(cv_id),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{cv_id}.pdf"'},
        )

    @routes.post("/api/profile/cvs/{cv_id}/select")
    def select_cv(cv_id: str, body: ProfileRevisionInput):
        return deps.profile_store.select_cv(cv_id, body.expected_revision)

    @routes.post("/api/profile/cvs/{cv_id}/revoke")
    def revoke_cv(cv_id: str, body: ProfileRevisionInput):
        return deps.profile_store.revoke_cv(cv_id, body.expected_revision)

    @routes.get("/api/profile/proficiency")
    def get_proficiency():
        return deps.profile_store.read_proficiency()

    @routes.post("/api/profile/proficiency/entries", status_code=201)
    def add_proficiency(body: ProficiencyCreateInput):
        return deps.profile_store.add_proficiency(
            concept=body.concept,
            comfort=body.comfort,
            notes=body.notes,
            expected_revision=body.expected_revision,
        )

    @routes.patch("/api/profile/proficiency/entries/{entry_id}")
    def update_proficiency(entry_id: str, body: ProficiencyUpdateInput):
        updates = {
            key: getattr(body, key)
            for key in ("concept", "comfort", "notes")
            if key in body.model_fields_set
        }
        return deps.profile_store.update_proficiency(
            entry_id, updates=updates, expected_revision=body.expected_revision
        )

    return routes


def _cv_record(deps: AppDeps, cv_id: str) -> dict[str, Any]:
    profile = deps.profile_store.read_profile()
    record = next((candidate for candidate in profile["cvs"] if candidate["id"] == cv_id), None)
    if record is None:
        from lab.errors import NotFound

        raise NotFound("CV version not found.")
    return record


def _validated_parse(parsed: object, parser: str) -> tuple[str, dict[str, Any] | None, str, dict[str, Any]]:
    if not isinstance(parsed, dict):
        raise ValueError("CV parser returned invalid data")
    canonical_text = parsed.get("canonical_text")
    native_document = parsed.get("native_document")
    parser_version = parsed.get("parser_version")
    diagnostics = parsed.get("diagnostics")
    if (
        not isinstance(canonical_text, str)
        or not isinstance(parser_version, str)
        or (native_document is not None and not isinstance(native_document, dict))
        or not isinstance(diagnostics, dict)
    ):
        raise ValueError("CV parser returned invalid data")
    result_parser = parsed.get("parser")
    if result_parser != parser:
        raise ValueError("CV parser identity did not match the requested parser")
    if not canonical_text.strip():
        diagnostics = {**diagnostics, "status": "error", "findings": [*diagnostics.get("findings", []), "No CV text was extracted."]}
    elif diagnostics.get("status") == "ready" and "note" not in diagnostics:
        diagnostics = {
            **diagnostics,
            "note": "No parser warnings; extraction fidelity remains unassessed.",
        }
    return canonical_text, native_document, parser_version, diagnostics
