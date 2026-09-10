# Learning Lab API

Install from this directory: `python -m pip install -e '.[test]'`.
Run one process: `uvicorn lab.main:app --host 127.0.0.1 --port 8765`.
Tests: `python -m pytest`.

`LEARNING_LAB_ROOT` overrides Code's sibling Learning directory.
`LEARNING_LAB_STATE_ROOT` overrides Code/.local; settings.json lives there.
`LEARNING_LAB_SETTINGS` optionally overrides the exact settings file (keep .local ignored).
`LEARNING_LAB_MAX_UPLOAD_BYTES` defaults to 25 MiB.
Do not run multiple workers: topic mutation locks are process-local.

Each topic is flat: topic.json, files.json, session.json, unique UTC upload-date-prefixed original PDFs,
and corresponding Markdown. DELETE archives metadata and preserves all originals.
Only explicit attachment IDs in the selected topic are read into model context.
Full user/assistant text and thinking are retained independently of model truncation.
Interrupted replies are marked incomplete. Attachments enter as untrusted user messages.
The fixed system scope rules are always prepended. No model tools are exposed.

The model integration imports `lab.models` lazily and calls the exact positional
`stream_chat(messages, model, think, context_limit)` contract in docs/API.md.
The model adapter owns truncation and must preserve system messages.

PDF conversion uses Python MarkItDown.convert_stream / text_content or
anydoc.to_markdown_bytes(data, "pdf"), directly selected by the multipart parser field.
No hosted OCR is enabled; scanned PDFs receive an actionable error and the original
remains viewable. See upstream APIs:
https://github.com/microsoft/markitdown
https://github.com/firecrawl/anydoc/blob/main/python/README.md

Browser requests accept only localhost:5173 and 127.0.0.1:5173 origins. Bind to
loopback only. This is a local single-user service, not an authenticated remote API.
Filesystem IDs reject traversal; root, topic and file symlinks are rejected.
An adversarial local process with write access to the data directory is outside
this service's isolation boundary; filesystem permissions remain necessary.
