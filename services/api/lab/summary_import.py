"""Pure construction and validation for immutable saved-summary conversation imports."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lab.contracts import Message, Session
from lab.errors import CorruptData
from lab.section_summary import SummarySource


class SummaryImportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    import_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_id: str = Field(min_length=1, max_length=80)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    section_id: str = Field(min_length=1, max_length=100)
    summary_id: str = Field(min_length=1, max_length=100)
    section_title: str
    model: str = Field(min_length=1, max_length=200)
    summary_created_at: datetime
    imported_at: datetime
    sources: list[SummarySource] = Field(min_length=1)


def deterministic_import_id(conversation_id: str, file_id: str, revision: str, summary_id: str) -> str:
    """Return the stable idempotency key for one saved summary in one destination conversation."""
    value = [conversation_id, file_id, revision, summary_id]
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_summary_import_message(
    conversation_id: str,
    *,
    file_id: str,
    revision: str,
    section_id: str,
    summary: dict[str, object],
    imported_at: str,
) -> Message:
    """Build a user-visible immutable snapshot message from a validated saved summary."""
    metadata = SummaryImportMetadata(
        schema_version=1,
        import_id=deterministic_import_id(conversation_id, file_id, revision, str(summary["id"])),
        file_id=file_id,
        revision=revision,
        section_id=section_id,
        summary_id=str(summary["id"]),
        section_title=str(summary["section_title"]),
        model=str(summary["model"]),
        summary_created_at=summary["created_at"],
        imported_at=imported_at,
        sources=summary["sources"],
    )
    content = (
        f"Saved section summary — {metadata.section_title}\n"
        "Generated summary, not verbatim PDF text.\n\n"
        f"{summary['content']}"
    )
    return {"role": "user", "content": content, "summary_import": metadata.model_dump(mode="json")}


def validated_summary_imports(session: Session, conversation_id: str) -> list[Message]:
    """Validate stored import metadata before exposing or deduplicating conversation messages."""
    messages = session.get("messages", [])
    if not isinstance(messages, list):
        raise CorruptData("Saved conversation messages are malformed.")
    imports: list[Message] = []
    for message in messages:
        if not isinstance(message, dict):
            raise CorruptData("Saved conversation message is malformed.")
        raw = message.get("summary_import")
        if raw is None:
            continue
        try:
            metadata = SummaryImportMetadata.model_validate(raw)
        except ValidationError as exc:
            raise CorruptData("Saved summary-import metadata is malformed.") from exc
        expected_id = deterministic_import_id(conversation_id, metadata.file_id, metadata.revision, metadata.summary_id)
        prefix = f"Saved section summary — {metadata.section_title}\nGenerated summary, not verbatim PDF text.\n\n"
        if (
            message.get("role") != "user"
            or not isinstance(message.get("content"), str)
            or not message["content"].startswith(prefix)
            or metadata.import_id != expected_id
        ):
            raise CorruptData("Saved summary-import message does not match its immutable metadata.")
        imports.append(message)
    return imports


def existing_summary_import(
    session: Session,
    conversation_id: str,
    *,
    file_id: str,
    revision: str,
    summary_id: str,
) -> Message | None:
    """Find an exact prior import, validating all import metadata encountered in the session."""
    target = deterministic_import_id(conversation_id, file_id, revision, summary_id)
    return next(
        (
            message
            for message in validated_summary_imports(session, conversation_id)
            if message["summary_import"]["import_id"] == target
        ),
        None,
    )


def find_section_summary(map_record: dict[str, object], section_id: str) -> dict[str, object] | None:
    """Find a section's current durable successful summary without consulting transient attempt text."""
    sections = map_record.get("sections")
    if not isinstance(sections, list):
        return None
    for section in sections:
        if not isinstance(section, dict):
            continue
        if section.get("id") == section_id:
            summary = section.get("last_summary")
            return summary if isinstance(summary, dict) else None
        nested = find_section_summary({"sections": section.get("children")}, section_id)
        if nested is not None:
            return nested
    return None
