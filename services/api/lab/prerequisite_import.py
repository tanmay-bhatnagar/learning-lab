"""Pure immutable prerequisite snapshots for an explicitly selected main conversation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from lab.contracts import Message, Session
from lab.errors import CorruptData, InvalidInput
from lab.section_summary import SummarySource


class PrerequisiteImportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    import_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    conversation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    topic_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    file_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    assessment_id: str = Field(min_length=1, max_length=100)
    map_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    section_id: str = Field(min_length=1, max_length=100)
    section_title: str = Field(min_length=1, max_length=1000)
    goal: str = Field(max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    assessment_finished_at: str
    imported_at: str
    sources: list[SummarySource] = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("assessment_finished_at", "imported_at")
    @classmethod
    def aware_timestamp(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Prerequisite snapshot timestamps must be ISO dates.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Prerequisite snapshot timestamps need a timezone.")
        return value


def prerequisite_import_id(conversation_id: str, file_id: str, assessment_id: str) -> str:
    """Identify one completed assessment snapshot in one explicit destination."""
    encoded = json.dumps([conversation_id, file_id, assessment_id], separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_prerequisite_import(
    conversation_id: str,
    *,
    assessment: dict[str, object],
    section_title: str,
    goal: str,
    model: str,
    learner_context: str,
    imported_at: str,
) -> Message:
    """Snapshot an already validated completed assessment and current self-reports without inference."""
    lines = [
        f"Saved prerequisites — {section_title}",
        "Suggestions are model-inferred, not verified prerequisites or proof of mastery.",
        f"Learning goal: {goal}",
        "",
        str(assessment["overview"]),
    ]
    for requirement in assessment["requirements"]:
        labels = " ".join(f"[{label}]" for label in requirement["source_labels"])
        lines.append(f"- {requirement['concept']}: {requirement['reason']} {labels}")
    if not assessment["requirements"]:
        lines.append("No preparatory concepts were proposed for this section.")
    if learner_context:
        lines.extend(
            ["", "Self-reports at import time (later requests use the latest saved answers):", learner_context]
        )
    content = "\n".join(lines)
    try:
        metadata = PrerequisiteImportMetadata(
            schema_version=1,
            import_id=prerequisite_import_id(
                conversation_id, str(assessment["file_id"]), str(assessment["assessment_id"])
            ),
            conversation_id=conversation_id,
            topic_id=assessment["topic_id"],
            file_id=assessment["file_id"],
            assessment_id=assessment["assessment_id"],
            map_revision=assessment["map_revision"],
            section_id=assessment["section_id"],
            section_title=section_title,
            goal=goal,
            model=model,
            assessment_finished_at=assessment["finished_at"],
            imported_at=imported_at,
            sources=assessment["sources"],
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        )
    except ValidationError as exc:
        raise InvalidInput("The completed prerequisite snapshot metadata is invalid.") from exc
    return {"role": "user", "content": content, "prerequisite_import": metadata.model_dump(mode="json")}


def validated_prerequisite_imports(session: Session, conversation_id: str) -> list[Message]:
    """Validate saved snapshot shape, destination and exact content before use or deduplication."""
    messages = session.get("messages", [])
    if not isinstance(messages, list):
        raise CorruptData("Saved conversation messages are malformed.")
    result = []
    for message in messages:
        if not isinstance(message, dict):
            raise CorruptData("Saved conversation message is malformed.")
        raw = message.get("prerequisite_import")
        if raw is None:
            continue
        try:
            metadata = PrerequisiteImportMetadata.model_validate(raw)
        except ValidationError as exc:
            raise CorruptData("Saved prerequisite snapshot metadata is malformed.") from exc
        content = message.get("content")
        if (
            message.get("role") != "user"
            or not isinstance(content, str)
            or not content.startswith(f"Saved prerequisites — {metadata.section_title}\n")
            or metadata.conversation_id != conversation_id
            or metadata.import_id != prerequisite_import_id(conversation_id, metadata.file_id, metadata.assessment_id)
            or metadata.content_sha256 != hashlib.sha256(content.encode()).hexdigest()
            or datetime.fromisoformat(metadata.imported_at) < datetime.fromisoformat(metadata.assessment_finished_at)
        ):
            raise CorruptData("Saved prerequisite snapshot does not match its immutable identity or content.")
        result.append(message)
    return result


def existing_prerequisite_import(
    session: Session, conversation_id: str, *, assessment_id: str, file_id: str
) -> Message | None:
    """Return an exact prior snapshot without replacing its historical self-reports."""
    target = prerequisite_import_id(conversation_id, file_id, assessment_id)
    return next(
        (
            message
            for message in validated_prerequisite_imports(session, conversation_id)
            if message["prerequisite_import"]["import_id"] == target
        ),
        None,
    )
