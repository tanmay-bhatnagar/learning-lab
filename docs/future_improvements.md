# Future improvements

## Post-release Docling versus MinerU benchmark

Status: proposal for a later structured-ingestion release.

The current app uses AnyDoc and MarkItDown. [Docling](https://github.com/docling-project/docling) is a future candidate because it provides a structured `DoclingDocument`, page and bounding-box provenance, hyperlinks, figure/caption relationships, referenced image export, and `HybridChunker` in one integration.

[MinerU](https://github.com/opendatalab/MinerU) remains a serious future parser candidate. Its high-quality hybrid/VLM pipeline reports stronger results on difficult scientific layouts in OmniDocBench and emits a useful native bundle:

- multimodal Markdown;
- `content_list.json` and `content_list_v2.json`;
- detailed `middle.json`;
- physical crops for figures, charts, tables, and equations;
- page indices, bounding boxes, captions, and asset paths;
- optional chart/image analysis.

MinerU is not proposed for the next parser increment because it adds a substantially larger model and dependency footprint, its agent chunking and hyperlink handling need additional integration, and its high-quality path is a poor fit for an 8 GB Jetson. These runtime costs may be acceptable because parsing is a one-time operation on the primary Mac.

### Intended execution model

If MinerU is evaluated later, run it as an isolated one-shot worker:

1. Finish or cancel any active model generation.
2. Let Ollama unload the conversational model.
3. Start the MinerU worker and parse the PDF.
4. Persist Markdown, structured JSON, and visual assets.
5. Exit the worker so MLX/PyTorch memory is released.
6. Reload the conversational model and index the parsed output.

Do not keep MinerU and the conversational model resident simultaneously when memory is constrained.

### Benchmark after first release

Use the same representative PDFs and compare the released Docling pipeline with a pinned MinerU stable release. Start with 10–20 difficult documents before running the full corpus.

Compare:

- missing, duplicated, or reordered text;
- heading hierarchy and multi-column reading order;
- table structure and cell values;
- equation preservation;
- hyperlink destination and anchor preservation;
- figure, chart, and flowchart crop quality;
- figure-caption association;
- page and bounding-box provenance;
- OCR behavior on mixed or scanned pages;
- parse time, peak memory, disk footprint, and worker startup/reload time;
- retrieval quality and prompt tokens using identical chunk/index settings.

Use public deterministic suites where applicable:

- [olmOCR-Bench](https://github.com/allenai/olmocr/tree/main/olmocr/bench) for text, tables, math, reading order, and scans;
- [OmniDocBench](https://github.com/opendatalab/OmniDocBench) for text edit distance, tables, formulas, and reading order;
- manual spot checks for hyperlinks and visual assets, which standard suites do not adequately score.

### Adoption rule

Do not add a generic multi-parser framework preemptively. If MinerU materially outperforms Docling on the Learning Lab corpus after release:

1. identify the smallest stable subset of MinerU outputs the application needs;
2. decide whether MinerU replaces Docling globally or handles only difficult document classes;
3. introduce a parser-neutral interchange model only when two active parsers actually require it;
4. migrate by reparsing immutable originals; never rewrite or delete historical derived artifacts silently.

References:

- MinerU output formats: https://opendatalab.github.io/MinerU/reference/output_files/
- MinerU hardware and backends: https://opendatalab.github.io/MinerU/quick_start/
- Docling document model: https://docling-project.github.io/docling/concepts/docling-document/
- Docling chunking: https://docling-project.github.io/docling/concepts/chunking/
