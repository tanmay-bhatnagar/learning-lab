"""Direct local Python adapters; converter choice never goes through a model.

Verified APIs: https://github.com/microsoft/markitdown and
https://github.com/firecrawl/anydoc/blob/main/python/README.md
"""
from io import BytesIO


def convert_pdf(data: bytes, parser: str) -> str:
    try:
        if parser == "markitdown":
            from markitdown import MarkItDown
            result = MarkItDown(enable_plugins=False).convert_stream(BytesIO(data), file_extension=".pdf")
            markdown = result.text_content
        elif parser == "anydoc":
            import anydoc
            markdown = anydoc.to_markdown_bytes(data, "pdf")
        else:
            raise ValueError("Choose markitdown or anydoc.")
    except ImportError as exc:
        raise ValueError(f"Install the backend dependencies for {parser}, then upload again.") from exc
    except Exception as exc:
        if "ocr" in type(exc).__name__.lower() or "ocr" in str(exc).lower():
            raise ValueError("This PDF requires OCR. Create a searchable PDF with a local OCR tool and upload it as a new original. No document was sent to a hosted OCR service.") from exc
        raise ValueError(f"{parser} could not convert this PDF ({type(exc).__name__}). Check that it is readable and not encrypted; scanned PDFs need local OCR before re-uploading.") from exc
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("No text was extracted. This may be a scanned PDF; create a searchable PDF with local OCR and upload that new file.")
    return markdown
