"""Real Docling smoke test using a generated PDF; no Learning topic is accessed."""
from __future__ import annotations

import json
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from lab.chunking import chunk_docling_document
from lab.docling_pipeline import parse_pdf_bytes


def synthetic_pdf() -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setTitle("Learning Lab Docling smoke test")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(72, 720, "Structured ingestion smoke test")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 690, "The calibration constant is 42 millivolts.")
    pdf.drawString(72, 670, "Reference: https://example.com/calibration")
    pdf.linkURL("https://example.com/calibration", (72, 666, 300, 682), relative=0)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(72, 620, "Signal flow")
    pdf.rect(72, 550, 110, 40)
    pdf.drawCentredString(127, 568, "Sensor")
    pdf.line(182, 570, 245, 570)
    pdf.line(235, 575, 245, 570)
    pdf.line(235, 565, 245, 570)
    pdf.rect(245, 550, 110, 40)
    pdf.drawCentredString(300, 568, "Calibrator")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def main() -> None:
    parsed = parse_pdf_bytes(synthetic_pdf(), filename="synthetic.pdf")
    chunks, chunk_warnings = chunk_docling_document(
        parsed.document, image_assets=parsed.images, embedding_model="nomic-embed-text",
    )
    assert "calibration constant" in parsed.markdown.lower()
    assert isinstance(parsed.docling, dict) and parsed.docling
    assert any(asset.kind == "page" for asset in parsed.images)
    assert chunks and any("calibration" in chunk["contextualized_text"].lower()
                          for chunk in chunks)
    print(json.dumps({
        "parser_version": parsed.parser_version,
        "markdown_chars": len(parsed.markdown),
        "chunks": len(chunks),
        "page_images": sum(asset.kind == "page" for asset in parsed.images),
        "figure_images": sum(asset.kind == "figure" for asset in parsed.images),
        "warnings": parsed.warnings + chunk_warnings,
        "hyperlink_preserved": "https://example.com/calibration" in json.dumps(parsed.docling),
    }, indent=2))


if __name__ == "__main__":
    main()
