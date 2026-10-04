from __future__ import annotations

from copy import deepcopy

import pytest
from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    PageItem,
    Size,
    TableCell,
    TableData,
)
from docling_core.types.doc.common.content_layer import ContentLayer

from lab.document_map import build_document_map


def _document() -> dict[str, object]:
    document = DoclingDocument(name="synthetic")
    document.add_text(label="text", text="Preamble", prov=None)
    first = document.add_heading("Repeated", level=1)
    document.add_text(label="text", text="Parent introduction", parent=first)
    child = document.add_heading("Child", level=2, parent=first)
    document.add_text(label="text", text="Child text", parent=child)
    document.add_text(label="text", text="Parent conclusion", parent=first)
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
    assert "Parent conclusion" in repeated[0]["text"]
    assert "Child text" in repeated[0]["children"][0]["text"]
    assert "Trailing text" in sections[-1]["text"]


def test_page_fallback_allocates_multipage_items_once_and_keeps_full_span() -> None:
    document = DoclingDocument(name="pages")
    box = BoundingBox(l=0, t=0, r=10, b=10)
    document.pages = {
        1: PageItem(page_no=1, size=Size(width=100, height=100)),
        2: PageItem(page_no=2, size=Size(width=100, height=100)),
    }
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
                TableCell(
                    text="Measure",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                ),
                TableCell(
                    text="Value",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                ),
                TableCell(
                    text="Accuracy",
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                ),
                TableCell(
                    text="0.9",
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                ),
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


def test_caption_is_owned_by_table_once_and_furniture_is_accounted_as_excluded() -> None:
    document = DoclingDocument(name="caption-and-furniture")
    caption = document.add_text(label=DocItemLabel.CAPTION, text="Table caption")
    document.add_table(
        TableData(
            num_rows=1,
            num_cols=1,
            table_cells=[
                TableCell(
                    text="Value",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                )
            ],
        ),
        caption=caption,
    )
    document.add_text(
        label=DocItemLabel.TEXT,
        text="Repeated page header",
        content_layer=ContentLayer.FURNITURE,
        parent=document.__dict__["furniture"],
    )

    result = _build(document.export_to_dict())
    assert result["coverage"]["total_source_items"] == 3
    assert result["coverage"]["accounted_source_items"] == 3
    assert result["coverage"]["total_units"] == 2
    table = next(unit for unit in result["units"] if unit["kind"] == "table")
    assert "Table caption" in table["text"]
    assert table["source_refs"] == [table["source_ref"], caption.self_ref]
    furniture = next(
        unit for unit in result["units"] if any("Furniture content" in warning for warning in unit["warnings"])
    )
    assert furniture["included"] is False
    assert all(furniture["id"] not in section["direct_unit_ids"] for section in result["sections"])


def test_invalid_native_schema_fails_instead_of_returning_empty_map() -> None:
    from lab.errors import CorruptData

    with pytest.raises(CorruptData):
        _build({"schema_name": "not-docling", "texts": []})


def test_dangling_native_body_reference_fails_as_corrupt_data() -> None:
    from lab.errors import CorruptData

    data = _document()
    data["body"]["children"].append({"$ref": "#/texts/9999"})

    with pytest.raises(CorruptData, match="reference"):
        _build(data)


def test_page_provenance_outside_saved_page_set_fails_visibly() -> None:
    from lab.errors import CorruptData

    document = DoclingDocument(name="bad-page")
    document.pages = {1: PageItem(page_no=1, size=Size(width=100, height=100))}
    document.add_text(
        label=DocItemLabel.TEXT,
        text="Unknown page text",
        prov=ProvenanceItem(
            page_no=999,
            bbox=BoundingBox(l=0, t=0, r=10, b=10),
            charspan=(0, 18),
        ),
    )

    with pytest.raises(CorruptData, match="page"):
        _build(document.export_to_dict())


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
