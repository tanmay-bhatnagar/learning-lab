# Learning Lab API

Install from this directory: `python -m pip install -e '.[test]'` (or `make setup` from Code).
Run one process: `uvicorn lab.asgi:create_app_factory --factory --host 127.0.0.1 --port 8765`; `make dev` starts it with the web app.
Tests: `make test` from Code. `docs/API.md` is the HTTP and model-adapter contract.

`LEARNING_LAB_ROOT` overrides Code's sibling Learning directory.
`LEARNING_LAB_STATE_ROOT` overrides Code/.local; settings.json lives there.
`LEARNING_LAB_SETTINGS` optionally overrides the exact settings file (keep .local ignored).
`LEARNING_LAB_MAX_UPLOAD_BYTES` defaults to 25 MiB.
`OLLAMA_BASE_URL` defaults to `http://localhost:11434`.
`DOCLING_ARTIFACTS_PATH` points Docling at local layout and table models (`make docling-models`; `make dev` sets it).
`EMBEDDING_TOKENIZER_ROOT` overrides the offline embedding tokenizer location (`make embedding-tokenizer`).
Do not run multiple workers: topic locks and the model-generation lock are process-local.

Each topic is flat: topic.json (name and optional learning goal), files.json, session.json,
unique UTC upload-date-prefixed original PDFs, and their derived artifacts. Originals are written once,
durably, and never overwritten. DELETE archives metadata and preserves all originals.

Docling is the default parser. It runs locally with OCR disabled and writes native JSON, Markdown,
chunk JSONL, page renders, figure crops and a parse manifest with extraction diagnostics, then
indexes chunks in the topic's `retrieval.sqlite`. Indexing is hybrid (SQLite FTS5 keywords plus Ollama
embeddings fused by rank) when the embedding model is available, and keyword-only with a warning when
it is not. MarkItDown and AnyDoc remain unindexed fallback converters that write Markdown only.
Scanned PDFs receive an actionable local-OCR error and the original remains viewable. An upload
interrupted mid-processing is reported as an `interrupted` error the next time files are listed.

Only explicit attachment IDs in the selected topic reach model context. Indexed files contribute
bounded retrieved passages with persistent citations; unindexed files are attached as whole Markdown.
Evidence and attachments enter as untrusted user messages, the fixed system scope rules and any
learning goal are prepended, and no model tools are exposed. The route budgets the prompt so evidence
passages are kept or dropped whole; the Ollama adapter (`lab.models`, imported lazily) asserts the
prompt fits when the route supplies context metadata. Full user and assistant text and thinking are
retained independently of request trimming, and interrupted replies are saved as incomplete.

Upstream converter APIs:
https://github.com/docling-project/docling
https://github.com/microsoft/markitdown
https://github.com/firecrawl/anydoc/blob/main/python/README.md
