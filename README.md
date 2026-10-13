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
6. For an on-demand outline, open **Map**, choose one ready Docling PDF, and click **Build outline**. Select a section and click **Generate summary**; nothing is generated merely by opening or selecting it. Inspect its source labels and original pages, then use **Add to “[conversation title]”** to add the saved generated context to your selected main conversation.

Open **My proficiency** to add your own concepts and familiarity. Upload a CV there, optionally rename it before uploading, then select the ready CV and inspect its complete extracted text. CV originals live outside topics under `../Profile/CVs/` with the exact chosen filename; duplicate names are rejected. Manual entries work without a CV.

In **Map**, select a section and choose **Generate prerequisites** with a visible learning goal. This uses the same selected local model in a fresh request, containing the complete section and literal extracted CV text. Each proposed concept asks for your familiarity independently; save any answers or notes explicitly. **Add to “[conversation title]”** saves the assessment in that existing main chat and activates its context. **Draft a follow-up** separately appends editable, unsent text to your composer. No side chat or automatic course is created.

Each later chat turn loads the latest compact saved proficiency and focused goal. **Always include CV** is off by default and saved separately for each conversation. Turning it on attaches the complete extracted CV text every turn; it is never retrieved as selected CV chunks. Required context that cannot fit is rejected visibly before sending. Revoking the CV prevents future use while preserving original files, saved assessments and CV-off historical learning context. Model suggestions remain advisory, and CV evidence never fills in your answers. Study the separate modules in [the My proficiency walkthrough](docs/proficiency.md).

The model selector reads from Ollama. Model changes apply to the next message. Indexed files are searched with SQLite FTS5 and, when the embedding model is installed, local embeddings plus reciprocal-rank fusion. The context limit is selected in Settings (up to 32,768 tokens); optional older history/evidence may be omitted from model requests while saved history remains intact. Runtime policy, the complete question and required learner/CV context are protected. There is no compaction yet.

Section summaries use the same selected Ollama model with a fresh request containing the runtime policy and complete section source. They do not include main-chat history, the learning goal or retrieved snippets. Oversized sections fail visibly rather than being truncated. Stop or failed regeneration preserves the last completed result; imported snapshots remain in ordinary saved chat history. Source labels identify supplied material, not proof that every generated claim is correct. See the [implementation and module study path](docs/reports/document-map/2026_10_05_document_map_implementation.md).

## Development instructions

Open this Code repository as the Codex project. [AGENTS.md](AGENTS.md) is the self-contained development policy, including research, alternatives, shared learning, proportional exploration, and reversible implementation for every agent. Six development procedures live in `.agents/skills/`; role configurations live in `.codex/agents/`. The browser backend loads the separate parent learning-agent policy before every chat request, regardless of the selected model. See [runtime policy loading](docs/runtime_policy.md) for configuration, failure behavior, and verification.

Consequential development checkpoints include a user walkthrough and durable dated decision notes explaining evidence, actual alternatives, rationale, tradeoffs, and remaining uncertainty. Browse the [feature report index](docs/reports/README.md) for saved research, design and implementation records. See [learning delivery](docs/engineering.md#learning-delivery-and-decision-records).

## Repository layout

```text
apps/web/          browser UI
services/api/      local API, parsers, Ollama gateway
.agents/skills/    six development procedures
.codex/agents/     six development role configurations
skills/            pinned parser reference instructions
evals/retrieval/   three-paper retrieval and trace baseline
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
