# Learning Lab — initial R1 foundation

A local browser app for topic-scoped PDF conversion and conversation with Ollama. This increment implements the UI, ingestion, local inference configuration and context meter. The full learning workflow, retrieval index/LangGraph tools, multimodal support, experiments and compaction come later.

## Run

Tested on macOS with Python 3.13 (the API supports Python 3.11+), Node 20+, and a running Ollama server at `127.0.0.1:11434`.

```sh
make setup
make dev
```

Open http://127.0.0.1:5173. The API uses loopback port 8765 when available, or automatically chooses a free loopback port. The launcher configures the frontend proxy accordingly. Stop the launcher with Ctrl-C. It stops its two child services, leaving Ollama and other user processes alone.

Create/select a topic, upload a PDF in Files, choose MarkItDown or anydoc, inspect the converted Markdown/original, and select the file for chat. Select an installed model in Settings. Reasoning controls depend on that model's actual support. External-provider cards are inactive placeholders; no API credentials are collected.

## Product layout

| Location | Responsibility |
| --- | --- |
| `apps/web/` | React/TypeScript browser UI and streaming client |
| `services/api/lab/` | FastAPI endpoints, scoped persistence, converter adapters, Ollama gateway and prompt budgeting |
| `services/api/tests/`, `tests/` | Backend boundaries and context/model contract tests |
| `skills/` | Pinned parser skill references; not exposed as model tools |
| `docs/` | API contract, skill provenance and validation notes |
| `scripts/` | Local launch and isolated end-to-end smoke test |
| `.local/` | Ignored application settings/runtime state |
| `../Learning/<topic>/` | Immutable originals, derived Markdown and complete topic conversation |

`Code/` is an independent Git repository, developed on `dev`; `main` is reserved for reviewed stable work. Code is exempt from the Second Brain's three-level directory limit. Learning material remains outside this repository. Do not commit model weights, private evidence, credentials, environments or generated dependencies.

## Context behavior

Default context is 8,192 tokens, with generation headroom reserved. Before inference, a conservative estimate budgets the prompt. Oldest conversation content is removed from the **request only**; a partial attachment can retain its newest text when necessary. Hard system rules remain. Full saved history and source files are preserved. This is truncation, not summarization or compaction. Consequently, the model may no longer see older evidence even though it remains in the UI.

The meter uses runtime counts when Ollama returns them and labels estimates otherwise. It measures the latest inference window, not disk size or all saved conversation. Exact preflight tokenization and compaction are later improvements.

## Local models

The selector discovers models installed in Ollama. Qwen3.5 4B Q8 is the smaller higher-precision option, and Qwen3.5 9B Q4 is a larger parameter-count option. Existing Gemma3 12B and DeepSeek R1 14B remain usable. Downloads are stored in Ollama's model store outside the brain. Model size is not total runtime RAM; long context also consumes memory. The initial app defaults to 8K context and caps selection at 32K. It does not distribute one model across Mac/Jetson.

## Boundaries and limitations

The model has no filesystem, shell, web or hardware tools. API paths validate topic and file identities and reject symlink escapes; document text is untrusted input. Uploads are local PDF conversion, without hosted OCR or external-provider inference. Scanned or encrypted PDFs may fail conversion. Extracted Markdown is not guaranteed to preserve equations, diagrams, layout or page citations; retain the original for comparison.

This loopback-only application has no remote-user authentication and is not intended for network exposure. It is not an OS sandbox for future arbitrary coding experiments. Those require separate isolation before enabling execution.

One conversation per topic is persisted in this increment. Full R1 learning functions and retrieval workflows have not been implemented yet. See `../2026_09_10_initial_build_scope.md` for the authorized milestone.

## Validate

```sh
make test
make build
.venv/bin/python scripts/smoke.py
.venv/bin/python scripts/smoke.py --model qwen3.5:4b-q8_0
```

The tested dependency lock includes `reportlab`. The smoke command creates a temporary synthetic PDF, verifies both real parsers and original-byte preservation, and optionally checks a real streamed model response. It never ingests test material into personal Learning topics.

Read `docs/skills-review.md` before later skill integration. The anydoc skill is official Firecrawl material; the MarkItDown wrapper is community-authored around Microsoft's library. Both are preserved with pinned provenance. Their broader upstream permissions/procedures do not override this project's boundaries.

`make setup` installs the tested versions in `services/api/requirements-macos-py313.lock`, then the frontend npm lock. The package metadata in `services/api/pyproject.toml` describes broader supported dependency ranges.
