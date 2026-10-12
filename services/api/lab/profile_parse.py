"""Parser boundary for a CV profile; never writes topic files or retrieval chunks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lab.docling_pipeline import parse_pdf_bytes
from lab.parsers import convert_pdf


def parse_profile_pdf(
    data: bytes,
    filename: str,
    parser: str,
    *,
    parser_map: dict[str, Any] | None = None,
    artifacts_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return the complete parser text and native Docling data without chunking."""
    if parser == "docling":
        parsed = parse_pdf_bytes(data, filename=filename, artifacts_path=artifacts_path)
        warnings = [warning.message for warning in parsed.warnings]
        return {
            "canonical_text": parsed.markdown,
            "native_document": parsed.docling,
            "parser": "docling",
            "parser_version": parsed.parser_version,
            "diagnostics": {
                "status": "error" if warnings else "ready",
                "findings": warnings,
            },
        }
    converter = (parser_map or {}).get(parser)
    markdown = converter(data, parser) if converter is not None else convert_pdf(data, parser)
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("No complete CV text was extracted by the selected parser.")
    return {
        "canonical_text": markdown,
        "native_document": None,
        "parser": parser,
        "parser_version": "unknown",
        "diagnostics": {
            "status": "ready",
            "findings": [],
            "note": "Extraction completed; fidelity was not independently assessed.",
        },
    }
