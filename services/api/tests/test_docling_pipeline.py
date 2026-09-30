import sys
from io import BytesIO
from types import ModuleType, SimpleNamespace

import pytest

from lab import chunking, docling_pipeline, parse_pipeline
from lab.docling_pipeline import ImageAsset, ParseArtifacts
from lab.storage import Store


class FakePIL:
    def __init__(self, payload=b"PNG"):
        self._payload = payload

    def save(self, buffer, format="PNG"):
        buffer.write(self._payload)


class FakeBBox:
    def model_dump(self, mode="json", by_alias=True, exclude_none=True):
        return {"l": 1.0, "t": 2.0, "r": 3.0, "b": 4.0, "coord_origin": "TOPLEFT"}


class FakeProv:
    def __init__(self, page_no=1):
        self.page_no = page_no
        self.bbox = FakeBBox()


class FakePageImage:
    def __init__(self, payload=b"page-png"):
        self._pil = FakePIL(payload)

    @property
    def pil_image(self):
        return self._pil


class FakePage:
    def __init__(self, payload=b"page-png"):
        self.image = FakePageImage(payload)


class FakePicture:
    def __init__(self, index=0, page_no=2, caption="Figure 1", payload=b"figure-png"):
        self.self_ref = f"#/pictures/{index}"
        self.prov = [FakeProv(page_no=page_no)]
        self.image = FakePageImage(payload)
        self._payload = payload
        self._caption = caption

    def get_image(self, document):
        return FakePIL(self._payload)

    def caption_text(self, document):
        return self._caption


class FakeDocument:
    def __init__(self):
        self.pages = {1: FakePage(b"page-one"), 2: FakePage(b"page-two")}
        self.pictures = [FakePicture(index=0, page_no=2, caption="Figure 1")]

    def export_to_markdown(self):
        return "# Title\n\nBody text."

    def export_to_dict(self):
        return {"name": "sample", "texts": []}


class FakeVersion:
    docling_version = "2.127.0"


class FakeConversionResult:
    def __init__(self, *, status="success", errors=None, document=None):
        self.status = status
        self.errors = errors or []
        self.document = document or FakeDocument()
        self.version = FakeVersion()


class FakeDocumentConverter:
    instances: list["FakeDocumentConverter"] = []
    last_stream = None
    last_options = None

    def __init__(self, allowed_formats=None, format_options=None):
        self.allowed_formats = allowed_formats
        self.format_options = format_options
        FakeDocumentConverter.instances.append(self)
        FakeDocumentConverter.last_options = format_options

    def convert(self, stream, **kwargs):
        FakeDocumentConverter.last_stream = stream
        self.convert_kwargs = kwargs
        return FakeConversionResult()


class FakePdfPipelineOptions:
    last_kwargs = None

    def __init__(self, **kwargs):
        FakePdfPipelineOptions.last_kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakePdfFormatOption:
    last_pipeline_options = None

    def __init__(self, *, pipeline_options=None, **kwargs):
        FakePdfFormatOption.last_pipeline_options = pipeline_options
        self.pipeline_options = pipeline_options


class FakeHybridChunker:
    instances: list["FakeHybridChunker"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeHybridChunker.instances.append(self)

    def chunk(self, document):
        meta = SimpleNamespace(
            doc_items=[SimpleNamespace(self_ref="#/pictures/0", prov=[FakeProv(page_no=2)])],
            headings=["Intro"],
        )
        yield SimpleNamespace(text="chunk body", meta=meta)

    def contextualize(self, chunk):
        return "Intro\nchunk body"


def _install_docling_mocks(monkeypatch):
    fake_docling = ModuleType("docling")
    fake_docling.chunking = ModuleType("docling.chunking")
    fake_docling.chunking.HybridChunker = FakeHybridChunker

    fake_datamodel = ModuleType("docling.datamodel")
    fake_base_models = ModuleType("docling.datamodel.base_models")
    fake_base_models.ConversionStatus = SimpleNamespace(
        FAILURE="failure",
        PARTIAL_SUCCESS="partial_success",
    )
    fake_base_models.InputFormat = SimpleNamespace(PDF="pdf")
    fake_base_models.DocumentStream = lambda name, stream: SimpleNamespace(name=name, stream=stream)

    fake_pipeline_options = ModuleType("docling.datamodel.pipeline_options")
    fake_pipeline_options.PdfPipelineOptions = FakePdfPipelineOptions

    fake_document_converter = ModuleType("docling.document_converter")
    fake_document_converter.DocumentConverter = FakeDocumentConverter
    fake_document_converter.PdfFormatOption = FakePdfFormatOption

    monkeypatch.setitem(sys.modules, "docling", fake_docling)
    monkeypatch.setitem(sys.modules, "docling.chunking", fake_docling.chunking)
    monkeypatch.setitem(sys.modules, "docling.datamodel", fake_datamodel)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", fake_base_models)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", fake_pipeline_options)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_document_converter)


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeDocumentConverter.instances.clear()
    FakeDocumentConverter.last_stream = None
    FakeDocumentConverter.last_options = None
    FakePdfPipelineOptions.last_kwargs = None
    FakePdfFormatOption.last_pipeline_options = None
    FakeHybridChunker.instances.clear()
    yield


def test_parse_pdf_bytes_returns_artifacts(monkeypatch):
    _install_docling_mocks(monkeypatch)
    artifacts = docling_pipeline.parse_pdf_bytes(
        b"%PDF-1.7\n",
        filename="notes.pdf",
        images_scale=2.0,
        artifacts_path="/tmp/models",
    )

    assert artifacts.markdown.startswith("# Title")
    assert artifacts.docling == {"name": "sample", "texts": []}
    assert artifacts.parser_version == "2.127.0"
    assert artifacts.document is not None
    assert FakeDocumentConverter.last_stream.name == "notes.pdf"
    assert isinstance(FakeDocumentConverter.last_stream.stream, BytesIO)
    assert FakeDocumentConverter.instances[-1].convert_kwargs == {
        "max_num_pages": 250,
        "max_file_size": 25 * 1024 * 1024,
    }

    options = FakePdfPipelineOptions.last_kwargs
    assert options["do_ocr"] is False
    assert options["do_table_structure"] is True
    assert options["generate_page_images"] is True
    assert options["generate_picture_images"] is True
    assert options["images_scale"] == 2.0
    assert options["artifacts_path"] == "/tmp/models"


def test_parse_pdf_bytes_uses_env_artifacts_path(monkeypatch):
    _install_docling_mocks(monkeypatch)
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", "/cache/docling")
    docling_pipeline.parse_pdf_bytes(b"%PDF-1.7\n")
    assert FakePdfPipelineOptions.last_kwargs["artifacts_path"] == "/cache/docling"


def test_parse_pdf_bytes_collects_flat_image_assets(monkeypatch):
    _install_docling_mocks(monkeypatch)
    artifacts = docling_pipeline.parse_pdf_bytes(b"%PDF-1.7\n")

    assert [asset.filename for asset in artifacts.images] == [
        "page_000001.png",
        "page_000002.png",
        "figure_000000.png",
    ]
    page = artifacts.images[0]
    assert page.id == "page_000001"
    assert page.kind == "page"
    assert page.page == 1
    assert page.bbox is None
    assert page.data == b"page-one"

    figure = artifacts.images[2]
    assert figure.id == "figure_000000"
    assert figure.kind == "figure"
    assert figure.page == 2
    assert figure.caption == "Figure 1"
    assert figure.doc_ref == "#/pictures/0"
    assert figure.bbox["l"] == 1.0


def test_parse_pdf_bytes_raises_on_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", ModuleType("docling.datamodel.base_models"))
    with pytest.raises(ValueError, match="Install the backend dependencies for docling"):
        docling_pipeline.parse_pdf_bytes(b"%PDF-1.7\n")


def test_parse_pdf_bytes_raises_on_conversion_failure(monkeypatch):
    _install_docling_mocks(monkeypatch)

    class FailingConverter(FakeDocumentConverter):
        def convert(self, stream, **kwargs):
            return FakeConversionResult(
                status="failure",
                errors=[SimpleNamespace(module_name="parser", error_message="broken", page_no=3)],
            )

    monkeypatch.setitem(
        sys.modules,
        "docling.document_converter",
        SimpleNamespace(
            DocumentConverter=FailingConverter,
            PdfFormatOption=FakePdfFormatOption,
        ),
    )

    with pytest.raises(ValueError, match="docling could not convert this PDF"):
        docling_pipeline.parse_pdf_bytes(b"%PDF-1.7\n")


def test_parse_pdf_bytes_explains_blocked_model_download(monkeypatch):
    _install_docling_mocks(monkeypatch)

    class OfflineConverter(FakeDocumentConverter):
        def convert(self, stream, **kwargs):
            raise RuntimeError("ConnectError: UNEXPECTED_EOF_WHILE_READING")

    monkeypatch.setitem(
        sys.modules,
        "docling.document_converter",
        SimpleNamespace(
            DocumentConverter=OfflineConverter,
            PdfFormatOption=FakePdfFormatOption,
        ),
    )

    with pytest.raises(ValueError, match="could not reach Hugging Face.*make docling-models"):
        docling_pipeline.parse_pdf_bytes(b"%PDF-1.7\n")


def test_parse_pdf_bytes_raises_on_empty_markdown(monkeypatch):
    _install_docling_mocks(monkeypatch)

    class EmptyDocument(FakeDocument):
        def export_to_markdown(self):
            return "   "

    class EmptyConverter(FakeDocumentConverter):
        def convert(self, stream, **kwargs):
            return FakeConversionResult(document=EmptyDocument())

    monkeypatch.setitem(
        sys.modules,
        "docling.document_converter",
        SimpleNamespace(
            DocumentConverter=EmptyConverter,
            PdfFormatOption=FakePdfFormatOption,
        ),
    )

    with pytest.raises(ValueError, match="No text was extracted"):
        docling_pipeline.parse_pdf_bytes(b"%PDF-1.7\n")


def test_parse_pdf_bytes_surfaces_partial_success_warnings(monkeypatch):
    _install_docling_mocks(monkeypatch)

    class PartialConverter(FakeDocumentConverter):
        def convert(self, stream, **kwargs):
            return FakeConversionResult(
                status="partial_success",
                errors=[SimpleNamespace(module_name="layout", error_message="skipped table", page_no=4)],
            )

    monkeypatch.setitem(
        sys.modules,
        "docling.document_converter",
        SimpleNamespace(
            DocumentConverter=PartialConverter,
            PdfFormatOption=FakePdfFormatOption,
        ),
    )

    artifacts = docling_pipeline.parse_pdf_bytes(b"%PDF-1.7\n")
    assert artifacts.warnings[0] == "Docling reported partial_success."
    assert "layout: skipped table (page 4)" in artifacts.warnings[1]


def test_chunk_docling_document_returns_json_ready_chunks(monkeypatch):
    _install_docling_mocks(monkeypatch)
    assets = [
        docling_pipeline.ImageAsset(
            id="figure_000000",
            filename="figure_000000.png",
            data=b"figure-png",
            kind="figure",
            page=2,
            bbox={"l": 1.0, "t": 2.0, "r": 3.0, "b": 4.0},
            caption="Figure 1",
            doc_ref="#/pictures/0",
        )
    ]

    chunks, warnings = chunking.chunk_docling_document(FakeDocument(), image_assets=assets)

    assert len(warnings) == 1
    assert "Unknown embedding model" in warnings[0]
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk["index"] == 0
    assert chunk["text"] == "chunk body"
    assert chunk["contextualized_text"] == "Intro\nchunk body"
    assert chunk["headings"] == ["Intro"]
    assert chunk["pages"] == [2]
    assert chunk["bboxes"][0]["page"] == 2
    assert chunk["picture_asset_ids"] == ["figure_000000"]


def test_enforce_embed_limit_splits_oversize_chunks_at_word_boundaries(monkeypatch):
    monkeypatch.setattr(chunking, "chunk_embed_token_limit", lambda model: 6)
    monkeypatch.setattr(chunking, "count_embedding_tokens",
                        lambda text, model, role=None: len(text.split()))
    record = {"text": "one two three four five six seven", "contextualized_text": "H\none two three four five six seven",
              "headings": ["H"], "pages": [3], "bboxes": [], "picture_asset_ids": []}

    pieces = chunking._enforce_embed_limit(record, "nomic-embed-text")

    assert [piece["text"] for piece in pieces] == ["one two three four five ", "six ", "seven"]
    assert "".join(piece["text"] for piece in pieces) == record["text"]
    assert all(piece["contextualized_text"].startswith("H\n") for piece in pieces)
    assert all(piece["pages"] == [3] and piece["split_for_embedding"] for piece in pieces)


def test_enforce_embed_limit_preserves_multiline_python_and_bounded_headings(monkeypatch):
    import ast

    source = 'def choose(flag):\n    if flag:\n        return "ready"\n    else:\n        return "stop"\n'
    headings = ["Code example"]
    limit = 32
    monkeypatch.setattr(chunking, "chunk_embed_token_limit", lambda model: limit)
    monkeypatch.setattr(chunking, "count_embedding_tokens", lambda text, model, role=None: len(text))
    record = {"text": source, "contextualized_text": source, "headings": headings,
              "pages": [1], "bboxes": [], "picture_asset_ids": []}

    pieces = chunking._enforce_embed_limit(record, "nomic-embed-text")
    reconstructed = "".join(piece["text"] for piece in pieces)

    assert len(pieces) > 1
    assert reconstructed == source
    ast.parse(reconstructed)
    assert all(len(piece["contextualized_text"]) <= limit for piece in pieces)


def test_enforce_embed_limit_keeps_fitting_chunks(monkeypatch):
    monkeypatch.setattr(chunking, "chunk_embed_token_limit", lambda model: 512)
    monkeypatch.setattr(chunking, "count_embedding_tokens", lambda text, model, role=None: 10)
    record = {"text": "short", "contextualized_text": "short", "headings": [], "pages": [],
              "bboxes": [], "picture_asset_ids": []}
    assert chunking._enforce_embed_limit(record, "nomic-embed-text") == [record]


def test_enforce_embed_limit_splits_indivisible_text_and_rejects_oversized_headings(monkeypatch):
    monkeypatch.setattr(chunking, "chunk_embed_token_limit", lambda model: 4)
    monkeypatch.setattr(chunking, "count_embedding_tokens",
                        lambda text, model, role=None: len(text.replace("\n", " ")))
    record = {"text": "abcdefghij", "contextualized_text": "abcdefghij", "headings": [],
              "pages": [], "bboxes": [], "picture_asset_ids": []}
    pieces = chunking._enforce_embed_limit(record, "nomic-embed-text")
    assert [piece["text"] for piece in pieces] == ["abcd", "efgh", "ij"]
    assert all(len(piece["text"]) <= 4 for piece in pieces)

    record["headings"] = ["heading too long"]
    with pytest.raises(ValueError, match="headings.*shorten or remove"):
        chunking._enforce_embed_limit(record, "nomic-embed-text")


def test_enforce_embed_limit_counts_embedding_special_tokens(monkeypatch):
    class RawTokenizer:
        def tokenize(self, text):
            return text.split()

        def encode(self, text, *, add_special_tokens):
            return self.tokenize(text) + (["[CLS]", "[SEP]"] if add_special_tokens else [])

    class ChunkTokenizer:
        tokenizer = RawTokenizer()

        def count_tokens(self, text):
            return len(self.tokenizer.tokenize(text))

        def get_tokenizer(self):
            return self.tokenizer

    from lab.embedding_config import count_with_chunk_tokenizer

    tokenizer = ChunkTokenizer()
    assert count_with_chunk_tokenizer("one two", "unknown-model", tokenizer) == 4
    monkeypatch.setattr(chunking, "chunk_embed_token_limit", lambda model: 4)
    record = {"text": "one two three four five six", "contextualized_text": "one two three four five six",
              "headings": [], "pages": [], "bboxes": [], "picture_asset_ids": []}
    pieces = chunking._enforce_embed_limit(record, "unknown-model", tokenizer=tokenizer)
    assert len(pieces) > 1
    assert all(count_with_chunk_tokenizer(piece["text"], "unknown-model", tokenizer) <= 4
               for piece in pieces)


def test_parse_persist_applies_embed_limit_to_figure_captions(monkeypatch, tmp_path):
    code_source = 'def choose(flag):\n    if flag:\n        return "ready"\n    else:\n        return "stop"\n'
    tokenizer = SimpleNamespace(count_tokens=len)
    asset = ImageAsset(
        id="figure_0", filename="figure.png", data=b"png", kind="figure",
        page=1, bbox=None, caption="captiontextlong", doc_ref="#/pictures/0",
    )
    parsed = ParseArtifacts(
        markdown="# Figure", docling={}, images=[asset], warnings=[],
        parser_version="test", document=object(),
    )
    monkeypatch.setattr(parse_pipeline, "parse_pdf_bytes", lambda *args, **kwargs: parsed)
    monkeypatch.setattr(parse_pipeline, "chunk_tokenizer", lambda model: (tokenizer, []))
    monkeypatch.setattr(parse_pipeline, "chunk_docling_document", lambda *args, **kwargs: ([{
        "index": 0, "text": code_source, "contextualized_text": code_source,
        "headings": [], "pages": [], "bboxes": [], "picture_asset_ids": [],
    }], []))
    monkeypatch.setattr(chunking, "chunk_embed_token_limit", lambda model: 8)
    store = Store(tmp_path / "topics", tmp_path / "settings.json")
    topic = store.create("Caption limits")["id"]

    _, records = parse_pipeline.parse_and_persist(
        store, topic, data=b"pdf", filename="figure.pdf",
        original_name="2026_09_30_figure.pdf", file_id="file1",
    )

    figure_chunks = [record for record in records if ":figure:" in record["chunk_id"]]
    assert records[0]["text"] == code_source
    assert "".join(record["text"] for record in figure_chunks) == "captiontextlong"
    assert all(len(record["text"]) <= 8 for record in figure_chunks)


def test_chunk_docling_document_raises_on_import_error(monkeypatch):
    empty = ModuleType("docling.chunking")
    monkeypatch.setitem(sys.modules, "docling.chunking", empty)
    if "docling" in sys.modules:
        monkeypatch.setattr(sys.modules["docling"], "chunking", empty, raising=False)
    with pytest.raises(ValueError, match="Install the backend dependencies for docling chunking"):
        chunking.chunk_docling_document(FakeDocument())[0]
