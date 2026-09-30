# Architecture and ownership

Current state on `dev` as of 30 September 2026. See the [interactive R1 map](../references/R1/system-map.html) for the system and its planned blocks, and the [R1 snapshot](../references/R1/README.md) for validation and remaining work.

## Runtime path

`Browser → topic API → topic-scoped retrieval → local Ollama model → streamed answer with saved citations`

A PDF upload follows a separate path: `browser → topic API → parser → bounded chunks and assets → topic SQLite index`. Selected MarkItDown and AnyDoc files use their Markdown as an unindexed chat attachment. Docling is the default structured parser.

The API app owns one model-generation lock shared by embedding and chat generation, keeping local model use serialized for bounded memory. Parsed artifact writes are atomic per file; the complete set of derived files is not transactional, and a failed parse can leave partial derived artifacts.

| Location | Owns |
| --- | --- |
| `apps/web/src/main.tsx`, `api.ts` | Browser workspace, files, settings, conversation and transport |
| `apps/web/src/citations.tsx`, `retrievalTrace.tsx` | Per-answer source display and retrieval inspection |
| `services/api/lab/http/` | HTTP routers, middleware, request schemas and app factory |
| `services/api/lab/config.py` | Frozen `AppConfig` and environment defaults |
| `services/api/lab/errors.py` | Domain error taxonomy |
| `services/api/lab/contracts.py` | Typed records and gateway/store protocols |
| `services/api/lab/ingest.py`, `chat_prompt.py`, `chat_session.py` | Pure upload, prompt and session transitions |
| `services/api/lab/parsers.py`, `docling_pipeline.py`, `parse_pipeline.py` | PDF converters, structured extraction and derived artifacts |
| `services/api/lab/chunking.py`, `embedding_config.py`, `hashing.py` | Chunk boundaries, tokenizer choice, embedding format and content hashes |
| `services/api/lab/index.py`, `retrieval.py` | Topic SQLite index, hybrid search and evidence assembly |
| `services/api/lab/models.py`, `context.py` | Local model gateway, streaming and prompt budget |
| `services/api/lab/storage.py` | Topic paths, original preservation, file and session records |
| `services/api/lab/asgi.py` | ASGI entry point |
| `scripts/dev.py`, `scripts/verify_workspace.py` | Development and verification lifecycle |

Personal topics and their PDFs live in `../Learning/<topic>/`, outside this Git repository. Tests override those roots. Model weights and runtime state remain local and ignored by Git.

## Current limits

- One saved conversation per topic. The selected context can be trimmed for a model request; the saved history remains complete. There is no compaction.
- Indexed Docling files support keyword and local embedding retrieval with a trace. Cited evidence is limited to passages retained in the model prompt. Saved citation page links open the topic-scoped original PDF at the cited page when supported by the browser viewer; invalid or out-of-range targets are shown unavailable.
- Each topic can store a validated user-authored learning goal. Chat supplies it as learning context, separate from retrieved evidence. Extraction diagnostics persist parser-reported failures and suspected limitations; a clean diagnostic run and legacy parser records remain fidelity-unassessed.
- Chat is one retrieval pass followed by model streaming. No LangGraph workflow, model tool calls, approval interrupts, understanding checks or progress memory exist yet.
- Topic and path validation is implemented. It is not an execution sandbox for future code, browser or device tools.
- The model adapter can send retrieved figure images to a vision-capable local model. General multimodal R2 behavior and Mac–Jetson deployment are not implemented.

## Contracts to preserve

- Every retrieval and persistence operation uses an explicit topic. Originals are immutable.
- A ready indexed file with a missing index fails visibly. An unfit prompt fails before the turn is saved.
- Tokenizer fallback is labeled approximate. Exact local counts include embedding prefixes and special tokens; oversized chunks retain their source whitespace.
- Citation metadata belongs to each saved assistant answer. It must agree with the evidence sent in that answer's model request.
- Stored-format changes require a compatibility decision. Future model tools, hardware access and web research require separate validation and authorization.

Coding conventions and validation gates live in [engineering.md](engineering.md).
