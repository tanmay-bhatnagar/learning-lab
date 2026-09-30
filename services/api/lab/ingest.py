"""Upload record transitions and ingest orchestration helpers."""

from __future__ import annotations

from typing import Literal

from lab.contracts import FileRecord, ParseUpdates

ParserName = Literal["docling", "markitdown", "anydoc"]


def processing_record(
    file_id: str,
    name: str,
    original_name: str,
    parser: ParserName,
) -> FileRecord:
    return {
        "id": file_id,
        "name": name,
        "original_name": original_name,
        "status": "processing",
        "parser": parser,
    }


def ready_from_parse(record: FileRecord, updates: ParseUpdates) -> FileRecord:
    return {**record, **updates, "status": "ready", "index_status": "not_indexed"}


def ready_from_markdown(record: FileRecord, markdown_name: str) -> FileRecord:
    return {
        **record,
        "status": "ready",
        "markdown_name": markdown_name,
        "index_status": "not_indexed",
        "extraction_diagnostics": {
            "status": "unassessed",
            "note": "Extraction fidelity was not assessed for this parser.",
            "findings": [],
        },
    }


def ready_from_docling(record: FileRecord, updates: ParseUpdates, index_result: dict[str, object]) -> FileRecord:
    result: FileRecord = {
        **record,
        **updates,
        "status": "ready",
        "index_status": "ready",
        "index_mode": str(index_result["mode"]),
        "embedding_model": index_result.get("embedding_model", ""),
    }
    if index_result.get("warning"):
        warnings = list(record.get("warnings") or [])
        warnings.append(str(index_result["warning"]))
        result["warnings"] = warnings
    return result


def ready_index_error(record: FileRecord, updates: ParseUpdates, exc: BaseException) -> FileRecord:
    warnings = list(record.get("warnings") or [])
    warnings.append(f"Document parsed, but indexing failed ({type(exc).__name__}): {exc}")
    return {
        **record,
        **updates,
        "status": "ready",
        "index_status": "error",
        "index_mode": "none",
        "warnings": warnings,
    }


def error_record(record: FileRecord, exc: BaseException) -> FileRecord:
    message = (
        str(exc)
        if isinstance(exc, ValueError)
        else f"Conversion failed ({type(exc).__name__}); check the PDF or use local OCR for scanned pages."
    )
    return {**record, "status": "error", "error": message}
