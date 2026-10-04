from __future__ import annotations

from copy import deepcopy

from docling_core.types.doc import DoclingDocument

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
    assert [section["title"] for section in sections] == ["Preamble", "Repeated", "Repeated", "Untitled section", "Unsectioned content"]
    repeated = [section for section in sections if section["title"] == "Repeated"]
    assert repeated[0]["id"] != repeated[1]["id"]
    assert repeated[0]["children"][0]["title"] == "Child"
    assert "Parent introduction" in repeated[0]["text"]
    assert "Child text" not in repeated[0]["text"]
    assert "Child text" in repeated[0]["children"][0]["text"]


def test_page_fallback_allocates_multipage_items_once_and_keeps_full_span() -> None:
    document = DoclingDocument(name="pages")
    document.add_text(label="text", text="Across pages", prov=None)
    result = _build(document.export_to_dict())

    assert result["outline_mode"] == "pages"
    unlocated = next(section for section in result["sections"] if section["title"] == "Unlocated content")
    assert unlocated["text"] == "Across pages"
    assert result["coverage"]["total_units"] == result["coverage"]["accounted_units"]


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
