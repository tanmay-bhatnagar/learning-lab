# Learning Lab

Learning Lab is a local, topic-scoped PDF learning app. It converts PDFs to Markdown, lets you inspect both versions, and provides a local Ollama chat interface with a visible context meter.

## Run locally

Requirements: macOS, Python 3.11+, Node 20+, and Ollama running at `127.0.0.1:11434`.

```sh
make setup   # first run only
make dev
```

Open http://127.0.0.1:5173. Keep the terminal open while using the app; press `Ctrl-C` to stop it. If port 8765 is busy, the launcher chooses another local API port automatically.

## Use it

1. Create a topic.
2. Open **Attached files** and drag in or browse for a PDF.
3. Review the original PDF and converted Markdown. AnyDoc is the default parser; MarkItDown is also available.
4. Select the document, choose an installed model in **Settings**, then chat.

The model selector reads from Ollama. Model changes apply to the next message. The app uses a 32,768-token context limit; once full, the oldest input is omitted from the model request while the saved conversation remains intact. There is no compaction yet.

## Repository layout

```text
apps/web/          browser UI
services/api/      local API, parsers, Ollama gateway
skills/            pinned parser instructions
data/external/     public parser-benchmark corpus and ignored model weights
docs/              API and validation notes
```

The application keeps personal topics, uploaded PDFs, conversions, and conversations in `../Learning/<topic>/`, outside this repository. The model has no shell, filesystem, web, or hardware tools.

## What is committed

The repository includes 107 public research PDFs and their source manifests in `data/external/benchmark_PDFs/` and `data/external/benchmark_manifests/`. These support the later parser comparison.

Model weights, temporary downloads, local environments, runtime state, credentials, and personal learning material are ignored. Never add a real API key or `.env` file.

## Checks

```sh
make test
make build
.venv/bin/python scripts/smoke.py
```

The smoke test uses a temporary synthetic PDF and does not write into a personal topic.
