"""Pure reconstruction of navigable source units from saved Docling data."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


BUILDER_VERSION = "document-map-v1"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _revision(file_id: str, source_revision: Mapping[str, str]) -> str:
    value = {"file_id": file_id, "source": dict(source_revision), "builder": BUILDER_VERSION}
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _item_id(revision: str, source_ref: str) -> str:
    digest = hashlib.sha256(f"{revision}:{source_ref}".encode()).hexdigest()[:20]
    return f"unit-{digest}"


def _section_id(revision: str, source_ref: str, ordinal: int) -> str:
    digest = hashlib.sha256(f"{revision}:{source_ref}:{ordinal}".encode()).hexdigest()[:20]
    return f"section-{digest}"


def _native_document(data: Mapping[str, object]) -> Any:
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError as exc:
        raise ValueError("Docling Core is required to build a document map.") from exc

    if not isinstance(data, Mapping):
        raise ValueError("Saved Docling data must be an object.")
    return DoclingDocument.model_validate(dict(data))


def _caption_refs(item: Any) -> set[str]:
    return {ref.cref for ref in getattr(item, "captions", []) or []}


def _caption_text(item: Any, document: Any) -> str:
    try:
        return item.caption_text(document).strip()
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return ""


def _serialize(item: Any, document: Any) -> tuple[str, str, list[str]]:
    name = type(item).__name__
    warnings: list[str] = []
    if name == "TableItem":
        text = item.export_to_markdown(doc=document).strip()
        caption = _caption_text(item, document)
        if caption and caption not in text:
            text = f"{caption}\n\n{text}" if text else caption
        return text, "table", warnings
    if name == "PictureItem":
        caption = _caption_text(item, document)
        warnings.append("Figure image content is not included; only extracted caption text is available.")
        return caption, "picture", warnings
    if name == "FormulaItem":
        return str(getattr(item, "text", "")).strip(), "formula", warnings
    if name == "ListItem":
        marker = str(getattr(item, "marker", "") or "").strip()
        text = str(getattr(item, "text", "")).strip()
        return f"{marker} {text}".strip(), "list_item", warnings
    if name in {"TextItem", "SectionHeaderItem", "TitleItem", "CodeItem", "FieldHeadingItem", "FieldValueItem"}:
        return str(getattr(item, "text", "")).strip(), "text", warnings
    return "", name, [f"Unsupported extracted item type: {name}."]


def _pages(item: Any) -> tuple[list[int], list[str]]:
    pages: list[int] = []
    warnings: list[str] = []
    for provenance in getattr(item, "prov", []) or []:
        page = getattr(provenance, "page_no", None)
        if isinstance(page, int) and not isinstance(page, bool) and page > 0:
            if page not in pages:
                pages.append(page)
        else:
            warnings.append("Invalid or missing page provenance was excluded.")
    return sorted(pages), warnings


def _walk_items(document: Any) -> list[Any]:
    from docling_core.types.doc import GroupItem

    items: list[Any] = []
    for item, _depth in document.iterate_items(with_groups=True, traverse_pictures=True):
        if item is document.body or item is document.furniture or isinstance(item, GroupItem):
            continue
        items.append(item)
    return items


def _source_units(document: Any, revision: str) -> tuple[list[dict[str, Any]], list[str]]:
    items = _walk_items(document)
    refs: set[str] = set()
    for item in items:
        source_ref = getattr(item, "self_ref", None)
        if not isinstance(source_ref, str) or not source_ref:
            raise ValueError("A native Docling item is missing its source reference.")
        if source_ref in refs:
            raise ValueError(f"Duplicate native Docling source reference: {source_ref}")
        refs.add(source_ref)

    owned_caption_refs = set().union(*(_caption_refs(item) for item in items)) if items else set()
    units: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in items:
        source_ref = item.self_ref
        if source_ref in owned_caption_refs:
            continue
        content, kind, item_warnings = _serialize(item, document)
        pages, page_warnings = _pages(item)
        item_warnings.extend(page_warnings)
        included = bool(content.strip())
        if not included and not item_warnings:
            item_warnings.append("Extracted item has no serializable text.")
        unit_warnings = list(dict.fromkeys(item_warnings))
        unit = {
            "id": _item_id(revision, source_ref),
            "source_ref": source_ref,
            "kind": kind,
            "text": content,
            "pages": pages,
            "included": included,
            "warnings": unit_warnings,
        }
        units.append(unit)
        warnings.extend(f"{source_ref}: {warning}" for warning in unit_warnings)
    return units, warnings


def _heading(item: Any) -> tuple[str, int] | None:
    if type(item).__name__ != "SectionHeaderItem":
        return None
    raw_level = getattr(item, "level", 1)
    level = raw_level if isinstance(raw_level, int) and raw_level > 0 else 1
    title = str(getattr(item, "text", "")).strip() or "Untitled section"
    return title, level


def _make_section(revision: str, source_ref: str, ordinal: int, title: str, level: int) -> dict[str, Any]:
    return {
        "id": _section_id(revision, source_ref, ordinal),
        "source_ref": source_ref,
        "title": title,
        "level": level,
        "pages": [],
        "text": "",
        "direct_unit_ids": [],
        "source_unit_ids": [],
        "children": [],
    }


def _append_unit(section: dict[str, Any], unit: dict[str, Any]) -> None:
    section["direct_unit_ids"].append(unit["id"])
    section["source_unit_ids"].append(unit["id"])
    if unit["included"]:
        section["text"] = "\n\n".join(part for part in (section["text"], unit["text"]) if part)
    section["pages"] = sorted(set(section["pages"]).union(unit["pages"]))


def _aggregate(section: dict[str, Any]) -> list[str]:
    values = list(section["direct_unit_ids"])
    for child in section["children"]:
        values.extend(_aggregate(child))
    section["source_unit_ids"] = values
    section["pages"] = sorted(
        set(section["pages"]).union(*(set(child["pages"]) for child in section["children"]))
    )
    return values


def _build_outline(
    document: Any,
    units: list[dict[str, Any]],
    revision: str,
) -> tuple[str, list[dict[str, Any]]]:
    source_to_unit = {unit["source_ref"]: unit for unit in units}
    items = _walk_items(document)
    has_headings = any(_heading(item) is not None for item in items)
    if not has_headings:
        by_page: dict[int, dict[str, Any]] = {}
        unlocated: dict[str, Any] | None = None
        for ordinal, unit in enumerate(units):
            if not unit["pages"]:
                if unlocated is None:
                    unlocated = _make_section(revision, "unlocated", ordinal, "Unlocated content", 1)
                _append_unit(unlocated, unit)
                continue
            first_page = unit["pages"][0]
            section = by_page.get(first_page)
            if section is None:
                section = _make_section(revision, f"page-{first_page}", first_page, f"Page {first_page}", 1)
                by_page[first_page] = section
            _append_unit(section, unit)
        sections = [by_page[page] for page in sorted(by_page)]
        if unlocated is not None:
            sections.append(unlocated)
        return "pages", sections

    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    preamble: dict[str, Any] | None = None
    active: dict[str, Any] | None = None
    ordinal = 0
    for item in items:
        heading = _heading(item)
        if heading is not None:
            title, level = heading
            ref = item.self_ref
            while stack and stack[-1]["level"] >= level:
                stack.pop()
            section = _make_section(revision, ref, ordinal, title, level)
            ordinal += 1
            if stack:
                stack[-1]["children"].append(section)
            else:
                roots.append(section)
            stack.append(section)
            active = section
            if ref in source_to_unit:
                _append_unit(section, source_to_unit[ref])
            continue
        unit = source_to_unit.get(getattr(item, "self_ref", ""))
        if unit is None:
            continue
        if active is None:
            if preamble is None:
                preamble = _make_section(revision, "preamble", ordinal, "Preamble", 1)
                ordinal += 1
            _append_unit(preamble, unit)
        else:
            _append_unit(active, unit)
    sections = ([preamble] if preamble is not None else []) + roots
    for section in roots:
        _aggregate(section)
    return "headings", sections


def build_document_map(
    native_data: Mapping[str, object],
    *,
    file_id: str,
    source_revision: Mapping[str, str],
) -> dict[str, Any]:
    """Build a stable outline and explicit accounting from saved native Docling JSON.

    This function performs no filesystem or model I/O and does not mutate either input.
    Unsupported native item schemas fail validation; recognized but unserializable items
    remain in coverage with a warning instead of disappearing silently.
    """
    if not isinstance(file_id, str) or not file_id:
        raise ValueError("A file ID is required to build a document map.")
    if not source_revision or any(not isinstance(value, str) or not value for value in source_revision.values()):
        raise ValueError("Source revision must identify the PDF and structured artifact.")
    document = _native_document(native_data)
    revision = _revision(file_id, source_revision)
    units, warnings = _source_units(document, revision)
    outline_mode, sections = _build_outline(document, units, revision)
    included = sum(unit["included"] for unit in units)
    excluded = len(units) - included
    return {
        "schema_version": 1,
        "builder_version": BUILDER_VERSION,
        "file_id": file_id,
        "revision": revision,
        "outline_mode": outline_mode,
        "sections": sections,
        "units": units,
        "coverage": {
            "total_units": len(units),
            "included_units": included,
            "excluded_units": excluded,
            "accounted_units": included + excluded,
        },
        "warnings": warnings,
    }
