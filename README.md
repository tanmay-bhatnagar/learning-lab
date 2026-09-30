# Learning Lab

Learning Lab is a local, topic-scoped PDF learning app. Docling preserves structured text, links, page provenance, tables, page renders, and figure crops; bounded hybrid retrieval then supplies relevant passages and visuals to a local Ollama chat interface.

## Run locally

Requirements: macOS, Python 3.11+, Node 20+, and Ollama running at `127.0.0.1:11434`.

```sh
make setup   # first run only
make dev
```

Open http://127.0.0.1:5173. Keep the terminal open while using the app; press `Ctrl-C` to stop it. If port 8765 is busy, the launcher chooses another local API port automatically.

Docling needs local layout and table models once:

```sh
make docling-models
```

They are stored in `data/external/modelweights/docling/` and are ignored by Git. This command needs a network that permits `huggingface.co`. If it is blocked, use AnyDoc or MarkItDown until you can download the Docling models through an approved connection.

Hybrid retrieval also needs the offline embedding tokenizer (default: `bert-base-uncased`, matching Ollama `nomic-embed-text` v1.5):

```sh
make embedding-tokenizer
```

Files land in `data/external/modelweights/tokenizers/bert-base-uncased/`. If Hugging Face is unreachable, the target bootstraps from the local Ollama `nomic-embed-text` GGUF vocabulary. Re-upload or re-index existing topics after changing embedding prefixes or tokenizer settings; upload already re-indexes via `replace_file`.

## Use it

1. Create a topic.
2. Open **Attached files** and drag in or browse for a PDF.
3. Review the original PDF and Docling Markdown. MarkItDown and AnyDoc remain available as unindexed fallbacks.
4. Install the embedding model configured in **Settings** (default: `ollama pull nomic-embed-text`) to enable semantic retrieval. Keyword retrieval remains available without it.
5. Select the document, choose an installed chat model in **Settings**, then chat.

The model selector reads from Ollama. Model changes apply to the next message. Indexed files are searched with SQLite FTS5 and, when the embedding model is installed, local embeddings plus reciprocal-rank fusion. The app uses a 32,768-token context limit; once full, the oldest input is omitted from the model request while the saved conversation remains intact. There is no compaction yet.

## Repository layout

```text
apps/web/          browser UI
services/api/      local API, parsers, Ollama gateway
skills/            pinned parser instructions
data/external/     public parser-benchmark corpus and ignored model weights
docs/              API and validation notes
references/R1/     current R1 map and project snapshot
```

The [R1 snapshot](references/R1/README.md) tracks what is built and what remains. Open the [interactive system map](references/R1/system-map.html) in a browser to inspect each block.

The application keeps personal topics, uploaded PDFs, conversions, and conversations in `../Learning/<topic>/`, outside this repository. The model has no shell, filesystem, web, or hardware tools.

## What is committed

The repository includes 107 public research PDFs and their source manifests in `data/external/benchmark_PDFs/` and `data/external/benchmark_manifests/`. These support the later parser comparison.

Model weights, temporary downloads, local environments, runtime state, credentials, and personal learning material are ignored. Never add a real API key or `.env` file.

## Checks

```sh
make test
make build
.venv/bin/python scripts/smoke.py
PYTHONPATH=services/api .venv/bin/python scripts/smoke_docling.py
PYTHONPATH=services/api DOCLING_ARTIFACTS_PATH=data/external/modelweights/docling .venv/bin/python scripts/chunking_demo.py
PYTHONPATH=services/api .venv/bin/python scripts/check_embedding_tokenizer_parity.py
```

Chunking uses Docling `contextualized_text` (headings + body) for indexed passages. Embeddings add Nomic task prefixes (`search_document:` at index time, `search_query:` at search time) with `truncate: false` so oversize chunks fail loudly instead of silently truncating.

The smoke tests use temporary synthetic PDFs and do not read or write a personal topic.
