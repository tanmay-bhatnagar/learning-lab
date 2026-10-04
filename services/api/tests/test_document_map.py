from __future__ import annotations

from copy import deepcopy

import pytest
from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    FormulaItem,
    ListItem,
    ProvenanceItem,
    SectionHeaderItem,
    TableCell,
    TableData,
)

from lab.document_map import build_document_map


def _document() -> dict[str, object]:
    document = DoclingDocument(name="synthetic")
    document.add_text(label="text", text="Preamble", prov=None)
    first = document.add_heading("Repeated", level=1)
    document.add_text(label="text", text="Parent introduction")
    child = document.add_heading("Child", level=2, parent=first)
    document.add_text(label="text", text="Child text", parent=child)
    document.add_heading("Repeated", level=1)
    document.add_heading("", level=1)
    document.add_text(label="text", text="Trailing text")
    return document.export_to_dict()


def _build(data: dict[str, object]) -> dict[str, object]:
    return build_document_map(
        data,
        file_id="paper",
        source_revision={"pdf_sha256": "pdf-rev", "docling_sha256": "doc-rev"},
    )


def test_native_outline_preserves_occurrences_preamble_and_parent_intro() -> None:
    result = _build(_document())

    assert result["outline_mode"] == "headings"
    sections = result["sections"]
    assert [section["title"] for section in sections] == ["Preamble", "Repeated", "Repeated", "Untitled section"]
    repeated = [section for section in sections if section["title"] == "Repeated"]
    assert repeated[0]["id"] != repeated[1]["id"]
    assert repeated[0]["children"][0]["title"] == "Child"
    assert "Parent introduction" in repeated[0]["text"]
    assert "Child text" not in repeated[0]["text"]
    assert "Child text" in repeated[0]["children"][0]["text"]
    assert "Trailing text" in sections[-1]["text"]


def test_page_fallback_allocates_multipage_items_once_and_keeps_full_span() -> None:
    document = DoclingDocument(name="pages")
    box = BoundingBox(l=0, t=0, r=10, b=10)
    document.add_text(
        label=DocItemLabel.TEXT,
        text="Across pages",
        prov=ProvenanceItem(page_no=1, bbox=box, charspan=(0, 13)),
    )
    item = document.texts[0]
    item.prov.append(ProvenanceItem(page_no=2, bbox=box, charspan=(0, 13)))
    result = _build(document.export_to_dict())

    assert result["outline_mode"] == "pages"
    assert [section["title"] for section in result["sections"]] == ["Page 1"]
    assert result["sections"][0]["text"] == "Across pages"
    assert result["units"][0]["pages"] == [1, 2]
    assert result["coverage"]["total_units"] == result["coverage"]["accounted_units"]


def test_native_serializer_includes_table_formula_and_list_content() -> None:
    document = DoclingDocument(name="structured")
    document.add_heading("Results", level=1)
    document.add_table(
        TableData(
            num_rows=2,
            num_cols=2,
            table_cells=[
                TableCell(text="Measure", start_row_offset_idx=0, end_row_offset_idx=1, start_col_offset_idx=0, end_col_offset_idx=1),
                TableCell(text="Value", start_row_offset_idx=0, end_row_offset_idx=1, start_col_offset_idx=1, end_col_offset_idx=2),
                TableCell(text="Accuracy", start_row_offset_idx=1, end_row_offset_idx=2, start_col_offset_idx=0, end_col_offset_idx=1),
                TableCell(text="0.9", start_row_offset_idx=1, end_row_offset_idx=2, start_col_offset_idx=1, end_col_offset_idx=2),
            ],
        )
    )
    document.add_formula(text="x = y + 1")
    document.add_list_item(text="First result", marker="1.", enumerated=True)

    result = _build(document.export_to_dict())
    serialized = "\n".join(unit["text"] for unit in result["units"])

    assert "Accuracy" in serialized and "0.9" in serialized
    assert "x = y + 1" in serialized
    assert "1. First result" in serialized
    assert result["coverage"]["accounted_units"] == len(result["units"])


def test_invalid_native_schema_fails_instead_of_returning_empty_map() -> None:
    with pytest.raises((ValueError, TypeError)):
        _build({"schema_name": "not-docling", "texts": []})


def test_source_units_and_revision_are_deterministic_and_inputs_are_immutable() -> None:
    data = _document()
    before = deepcopy(data)

    first = _build(data)
    second = _build(data)
    changed = build_document_map(
        data,
        file_id="paper",
        source_revision={"pdf_sha256": "different", "docling_sha256": "doc-rev"},
    )

    assert data == before
    assert first == second
    assert first["revision"] != changed["revision"]
