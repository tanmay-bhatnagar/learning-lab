"""Docling Standard Pipeline adapter for in-memory PDF parsing.

Uses Docling 2.127 APIs: ``DocumentStream``, ``DocumentConverter``, and
``PdfPipelineOptions`` with OCR disabled, table structure enabled, and page/picture
image generation. Optional model cache directory via ``DOCLING_ARTIFACTS_PATH``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class ImageAsset:
    """Flat image artifact; ``filename`` is a basename only (callers add prefixes)."""

    id: str
    filename: str
    data: bytes
    kind: Literal["page", "figure"]
    page: int | None
    bbox: dict[str, Any] | None
    caption: str | None
    doc_ref: str | None


@dataclass(frozen=True)
class ParseArtifacts:
    """Docling parse output for persistence and immediate chunking."""

    markdown: str
    docling: dict[str, Any]
    images: list[ImageAsset]
    warnings: list[str]
    parser_version: str
    document: Any


def _artifacts_path(explicit: str | Path | None) -> str | Path | None:
    if explicit is not None:
        return explicit
    env = os.environ.get("DOCLING_ARTIFACTS_PATH", "").strip()
    return env or None


def _build_converter(*, images_scale: float, artifacts_path: str | Path | None):
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        raise ValueError(
            "Install the backend dependencies for docling, then upload again."
        ) from exc

    pipeline_options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        generate_page_images=True,
        generate_picture_images=True,
        images_scale=images_scale,
        artifacts_path=artifacts_path,
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        },
    )


def _bbox_to_dict(bbox) -> dict[str, Any]:
    return bbox.model_dump(mode="json", by_alias=True, exclude_none=True)


def _pil_to_png_bytes(pil_image) -> bytes:
    buffer = BytesIO()
    pil_image.save(buffer, format="PNG")
    return buffer.getvalue()


def _collect_warnings(result) -> list[str]:
    from docling.datamodel.base_models import ConversionStatus

    warnings: list[str] = []
    if result.status == ConversionStatus.PARTIAL_SUCCESS:
        warnings.append("Docling reported partial_success.")
    for error in result.errors:
        page = f" (page {error.page_no})" if error.page_no is not None else ""
        warnings.append(f"{error.module_name}: {error.error_message}{page}")
    return warnings


def _collect_image_assets(document) -> list[ImageAsset]:
    assets: list[ImageAsset] = []

    for page_no in sorted(document.pages.keys()):
        page = document.pages[page_no]
        if page.image is None:
            continue
        pil_image = page.image.pil_image
        if pil_image is None:
            continue
        asset_id = f"page_{page_no:06d}"
        assets.append(
            ImageAsset(
                id=asset_id,
                filename=f"{asset_id}.png",
                data=_pil_to_png_bytes(pil_image),
                kind="page",
                page=page_no,
                bbox=None,
                caption=None,
                doc_ref=None,
            )
        )

    for index, picture in enumerate(document.pictures):
        pil_image = picture.get_image(document)
        if pil_image is None and picture.image is not None:
            pil_image = picture.image.pil_image
        if pil_image is None:
            continue
        page_no: int | None = None
        bbox: dict[str, Any] | None = None
        if picture.prov:
            page_no = picture.prov[0].page_no
            bbox = _bbox_to_dict(picture.prov[0].bbox)
        caption = picture.caption_text(document).strip() or None
        asset_id = f"figure_{index:06d}"
        assets.append(
            ImageAsset(
                id=asset_id,
                filename=f"{asset_id}.png",
                data=_pil_to_png_bytes(pil_image),
                kind="figure",
                page=page_no,
                bbox=bbox,
                caption=caption,
                doc_ref=picture.self_ref,
            )
        )

    return assets


def parse_pdf_bytes(
    data: bytes,
    *,
    filename: str = "document.pdf",
    images_scale: float = 1.0,
    artifacts_path: str | Path | None = None,
    max_pages: int = 250,
) -> ParseArtifacts:
    """Parse PDF bytes through Docling's Standard Pipeline."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("PDF data must be a non-empty byte string.")

    try:
        from docling.datamodel.base_models import ConversionStatus, DocumentStream
    except ImportError as exc:
        raise ValueError(
            "Install the backend dependencies for docling, then upload again."
        ) from exc

    stream = DocumentStream(name=filename, stream=BytesIO(data))
    converter = _build_converter(
        images_scale=images_scale,
        artifacts_path=_artifacts_path(artifacts_path),
    )

    try:
        result = converter.convert(
            stream,
            max_num_pages=max_pages,
            max_file_size=25 * 1024 * 1024,
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}".lower()
        if any(marker in detail for marker in ("connecterror", "unexpected_eof", "huggingface",
                                                "proxyerror", "snapshot_download", "403 forbidden")):
            raise ValueError(
                "Docling could not reach Hugging Face to obtain its local models. Connect through an "
                "approved network that permits huggingface.co, run `make docling-models` from Code, "
                "then retry. Until then, choose AnyDoc or MarkItDown."
            ) from exc
        if any(marker in detail for marker in ("filenotfounderror", "model artifact")):
            raise ValueError(
                "Docling's local models are not installed. Run `make docling-models` from Code, "
                "then retry. Until then, choose AnyDoc or MarkItDown."
            ) from exc
        if "ocr" in type(exc).__name__.lower() or "ocr" in str(exc).lower():
            raise ValueError(
                "This PDF requires OCR. Create a searchable PDF with a local OCR tool "
                "and upload it as a new original. No document was sent to a hosted OCR service."
            ) from exc
        raise ValueError(
            f"docling could not convert this PDF ({type(exc).__name__}). "
            "Check that it is readable and not encrypted; scanned PDFs need local OCR before re-uploading."
        ) from exc

    if result.status == ConversionStatus.FAILURE:
        detail = "; ".join(_collect_warnings(result)) or "conversion failed"
        raise ValueError(f"docling could not convert this PDF: {detail}")

    document = result.document
    markdown = document.export_to_markdown()
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError(
            "No text was extracted. This may be a scanned PDF; create a searchable PDF "
            "with local OCR and upload that new file."
        )

    return ParseArtifacts(
        markdown=markdown,
        docling=document.export_to_dict(),
        images=_collect_image_assets(document),
        warnings=_collect_warnings(result),
        parser_version=result.version.docling_version,
        document=document,
    )
