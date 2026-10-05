"""Validated, topic-scoped persistence for explicit document-map builds."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .document_map import BUILDER_VERSION, build_document_map
from .errors import Conflict, CorruptData, InvalidInput, NotFound
from .section_summary import (
    SavedSummary,
    SummaryAttempt,
    SummarySource,
    saved_source_metadata,
    section_sources,
    source_digest,
    validate_source_markers,
)
from .storage import Store, read_bytes, read_json, write_json

MAP_SCHEMA_VERSION = 1
SUMMARY_STATE = {"latest_attempt": None, "last_summary": None}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MapUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_ref: str
    source_refs: list[str]
    kind: str
    content_layer: Literal["body", "furniture"]
    text: str
    pages: list[int]
    included: bool
    warnings: list[str]


class MapSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_ref: str
    title: str
    level: int = Field(ge=1)
    pages: list[int]
    text: str
    direct_unit_ids: list[str]
    source_unit_ids: list[str]
    children: list[MapSection]
    latest_attempt: SummaryAttempt | None = None
    last_summary: SavedSummary | None = None


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_units: int = Field(ge=0)
    included_units: int = Field(ge=0)
    excluded_units: int = Field(ge=0)
    accounted_units: int = Field(ge=0)
    total_source_items: int = Field(ge=0)
    accounted_source_items: int = Field(ge=0)


class MapSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[MAP_SCHEMA_VERSION]
    builder_version: str
    file_id: str
    revision: str
    source_revision: dict[str, str]
    outline_mode: Literal["headings", "pages"]
    sections: list[MapSection]
    units: list[MapUnit]
    coverage: Coverage
    warnings: list[str]


class StoredMap(MapSnapshot):
    history: list[MapSnapshot]


def map_filename(file_id: str) -> str:
    """Return the deterministic per-file map name after Store ID validation."""
    from .storage import valid_id

    return f"{valid_id(file_id)}.map.json"


def _validated_map(value: object, *, expected_file_id: str | None = None) -> dict[str, object]:
    try:
        record = StoredMap.model_validate(value)
    except ValidationError as exc:
        raise CorruptData("Saved document map is unsupported or malformed; rebuild it to continue.") from exc
    if expected_file_id is not None and record.file_id != expected_file_id:
        raise CorruptData("Saved document map belongs to a different file.")
    _validate_snapshot(record, expected_file_id=expected_file_id)
    for snapshot in record.history:
        if snapshot.file_id != record.file_id:
            raise CorruptData("Saved document-map history belongs to a different file.")
        _validate_snapshot(snapshot, expected_file_id=record.file_id)
    return record.model_dump(mode="json")


def _validate_snapshot(record: MapSnapshot, *, expected_file_id: str | None) -> None:
    if expected_file_id is not None and record.file_id != expected_file_id:
        raise CorruptData("Saved document map belongs to a different file.")
    if set(record.source_revision) != {"pdf_sha256", "docling_sha256"} or any(
        SHA256.fullmatch(value) is None for value in record.source_revision.values()
    ):
        raise CorruptData("Saved document map has invalid source identity metadata.")
    if record.revision != _revision_for(record.file_id, record.source_revision, record.builder_version):
        raise CorruptData("Saved document map revision does not match its source identity.")
    unit_ids = [unit.id for unit in record.units]
    if len(unit_ids) != len(set(unit_ids)):
        raise CorruptData("Saved document map has duplicate source-unit identities.")
    unit_id_set = set(unit_ids)
    source_refs = [source_ref for unit in record.units for source_ref in unit.source_refs]
    if len(source_refs) != len(set(source_refs)):
        raise CorruptData("Saved document map accounts for a native source item more than once.")
    if any(not unit.source_refs or unit.source_refs[0] != unit.source_ref for unit in record.units):
        raise CorruptData("Saved document map source aliases do not identify their canonical unit.")

    section_ids: set[str] = set()
    direct_unit_ids: list[str] = []

    def validate_sections(sections: list[MapSection]) -> None:
        for section in sections:
            if section.id in section_ids:
                raise CorruptData("Saved document map has duplicate section identities.")
            section_ids.add(section.id)
            if len(section.direct_unit_ids) != len(set(section.direct_unit_ids)):
                raise CorruptData("Saved document map section repeats a direct source unit.")
            direct_unit_ids.extend(section.direct_unit_ids)
            if len(section.source_unit_ids) != len(set(section.source_unit_ids)):
                raise CorruptData("Saved document map section repeats a scoped source unit.")
            if any(unit_id not in unit_id_set for unit_id in section.direct_unit_ids):
                raise CorruptData("Saved document map refers to a missing source unit.")
            if any(unit_id not in unit_id_set for unit_id in section.source_unit_ids):
                raise CorruptData("Saved document map scope refers to a missing source unit.")
            descendants = set(section.direct_unit_ids)
            for child in section.children:
                descendants.update(child.source_unit_ids)
            expected = [unit_id for unit_id in unit_ids if unit_id in descendants]
            if expected != section.source_unit_ids:
                raise CorruptData("Saved document map section scope is inconsistent with its children.")
            validate_sections(section.children)

    validate_sections(record.sections)
    if len(direct_unit_ids) != len(set(direct_unit_ids)):
        raise CorruptData("Saved document map assigns one source unit to multiple sections.")
    eligible_units = {unit.id for unit in record.units if unit.content_layer == "body"}
    if set(direct_unit_ids) != eligible_units:
        raise CorruptData("Saved document map leaves body source units without a section owner.")
    coverage = record.coverage
    if (
        coverage.total_units != len(record.units)
        or coverage.included_units != sum(unit.included for unit in record.units)
        or coverage.included_units + coverage.excluded_units != coverage.total_units
        or coverage.accounted_units != coverage.total_units
        or coverage.total_source_items != len(source_refs)
        or coverage.accounted_source_items != len(source_refs)
    ):
        raise CorruptData("Saved document map coverage accounting is inconsistent.")
    snapshot = record.model_dump(mode="json")

    def validate_summary_state(sections: list[MapSection]) -> None:
        for section in sections:
            attempt = section.latest_attempt
            summary = section.last_summary
            if attempt is None and summary is None:
                validate_summary_state(section.children)
                continue
            sources = section_sources(snapshot, section.model_dump(mode="json"))
            digest = source_digest(sources)
            labels = [str(source["label"]) for source in sources]
            if attempt is not None:
                if (
                    attempt.revision != record.revision
                    or attempt.section_id != section.id
                    or attempt.source_sha256 != digest
                    or (attempt.status == "generating") != (attempt.finished_at is None)
                ):
                    raise CorruptData("Saved section-summary attempt does not match its map revision or source scope.")
                if attempt.prompt_context.get("limit") != attempt.context_limit:
                    raise CorruptData("Saved section-summary attempt context does not match its request metadata.")
                if attempt.status == "completed":
                    try:
                        validate_source_markers(attempt.content, labels)
                    except InvalidInput as exc:
                        raise CorruptData("Completed section-summary attempt has invalid source labels.") from exc
                    if summary is None or summary.id != attempt.id or summary.content != attempt.content:
                        raise CorruptData("Completed section-summary attempt is missing its durable summary.")
                    if (
                        summary.model != (attempt.actual_model or attempt.model)
                        or summary.policy_sha256 != attempt.policy_sha256
                        or summary.prompt_version != attempt.prompt_version
                        or summary.context_limit != attempt.context_limit
                        or summary.think != attempt.think
                        or summary.created_at != attempt.finished_at
                    ):
                        raise CorruptData("Completed section-summary and attempt provenance disagree.")
            if summary is not None:
                if (
                    summary.revision != record.revision
                    or summary.section_id != section.id
                    or summary.section_title != section.title
                    or summary.source_sha256 != digest
                    or summary.sources
                    != [SummarySource.model_validate(item) for item in saved_source_metadata(sources)]
                ):
                    raise CorruptData("Saved section summary does not match its map revision or source provenance.")
                try:
                    validate_source_markers(summary.content, labels)
                except InvalidInput as exc:
                    raise CorruptData("Saved section summary has invalid source labels.") from exc
                if attempt is not None and attempt.id == summary.id and attempt.status != "completed":
                    raise CorruptData("A saved summary points at a non-completed attempt.")
            validate_summary_state(section.children)

    validate_summary_state(record.sections)


def _current_revision(file_id: str, source_revision: dict[str, str]) -> str:
    return _revision_for(file_id, source_revision, BUILDER_VERSION)


def _revision_for(file_id: str, source_revision: dict[str, str], builder_version: str) -> str:
    value = {"file_id": file_id, "source": source_revision, "builder": builder_version}
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _with_summary_states(map_data: dict[str, object]) -> dict[str, object]:
    sections = map_data["sections"]
    return {
        **map_data,
        "sections": [
            {
                **section,
                **SUMMARY_STATE,
                "children": _with_summary_states({"sections": section["children"]})["sections"],
            }
            for section in sections
        ],
    }


def _source_record(store: Store, topic: str, file_id: str) -> tuple[dict[str, object], dict[str, str]]:
    file_record = store.file(topic, file_id)
    if file_record.get("status") != "ready":
        raise Conflict(file_record.get("error", "Document conversion is not complete."))
    if file_record.get("parser") != "docling" or not file_record.get("docling_name"):
        raise Conflict("A ready Docling structured artifact is required to build a document map.")
    original_name = file_record.get("original_name")
    docling_name = file_record.get("docling_name")
    if not isinstance(original_name, str) or not isinstance(docling_name, str):
        raise CorruptData("Ready Docling file record is missing its original or structured artifact name.")
    original_bytes = read_bytes(store.file_path(topic, original_name))
    docling_bytes = read_bytes(store.file_path(topic, docling_name))
    docling_data = read_json(store.file_path(topic, docling_name))
    if not isinstance(docling_data, dict):
        raise CorruptData("Saved Docling artifact must contain a JSON object.")
    source_revision = {
        "pdf_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "docling_sha256": hashlib.sha256(docling_bytes).hexdigest(),
    }
    return docling_data, source_revision


def _stored_path(store: Store, topic: str, file_id: str):
    return store.file_path(topic, map_filename(file_id))


def _read_saved_map(store: Store, topic: str, file_id: str) -> dict[str, object] | None:
    path = _stored_path(store, topic, file_id)
    missing = object()
    value = read_json(path, missing)
    if value is missing:
        return None
    return _validated_map(value, expected_file_id=file_id)


def _map_response(
    store: Store,
    topic: str,
    file_id: str,
) -> dict[str, object]:
    _, source_revision = _source_record(store, topic, file_id)
    saved = _read_saved_map(store, topic, file_id)
    if saved is None:
        return {"status": "not_built", "map": None}
    current_revision = _current_revision(file_id, source_revision)
    return {"status": "ready" if saved["revision"] == current_revision else "stale", "map": saved}


def get_document_map(store: Store, topic: str, file_id: str) -> dict[str, object]:
    """Read map state without creating or repairing a stored map."""
    return _map_response(store, topic, file_id)


def build_or_rebuild_document_map(store: Store, topic: str, file_id: str) -> dict[str, object]:
    """Build an outline explicitly, preserving same-revision state and prior revisions."""
    native_data, source_revision = _source_record(store, topic, file_id)
    path = _stored_path(store, topic, file_id)
    previous = _read_saved_map(store, topic, file_id)
    generated = _with_summary_states(build_document_map(native_data, file_id=file_id, source_revision=source_revision))
    if previous is not None and previous["revision"] == generated["revision"]:
        generated["history"] = previous["history"]
        generated["sections"] = _preserve_section_summaries(generated["sections"], previous["sections"])
    else:
        snapshots = list(previous["history"]) if previous is not None else []
        if previous is not None:
            snapshots.append({key: value for key, value in previous.items() if key != "history"})
        generated["history"] = snapshots
    generated["schema_version"] = MAP_SCHEMA_VERSION
    generated["source_revision"] = source_revision
    validated = _validated_map(generated, expected_file_id=file_id)
    write_json(path, validated)
    return {"status": "ready", "map": validated}


def _preserve_section_summaries(
    generated: list[dict[str, object]],
    previous: list[dict[str, object]],
) -> list[dict[str, object]]:
    previous_by_id = {section["id"]: section for section in _flatten_sections(previous)}

    def preserve(sections: list[dict[str, object]]) -> list[dict[str, object]]:
        result = []
        for section in sections:
            old = previous_by_id.get(section["id"], {})
            result.append(
                {
                    **section,
                    "latest_attempt": old.get("latest_attempt"),
                    "last_summary": old.get("last_summary"),
                    "children": preserve(section["children"]),
                }
            )
        return result

    return preserve(generated)


def _flatten_sections(sections: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for section in sections:
        result.append(section)
        result.extend(_flatten_sections(section["children"]))
    return result


def get_document_map_section(
    store: Store,
    topic: str,
    file_id: str,
    section_id: str,
) -> dict[str, object]:
    """Return one section's complete canonical source scope for later summaries."""
    response = _map_response(store, topic, file_id)
    saved = response["map"]
    if saved is None:
        raise Conflict("Build the document outline before opening a section.")
    matching = next((section for section in _flatten_sections(saved["sections"]) if section["id"] == section_id), None)
    if matching is None:
        raise NotFound("Section not found in the selected document map.")
    unit_ids = set(matching["source_unit_ids"])
    source_units = [unit for unit in saved["units"] if unit["id"] in unit_ids]
    return {
        "status": response["status"],
        "section": matching,
        "source_units": source_units,
    }
