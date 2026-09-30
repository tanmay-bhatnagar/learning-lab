# Architecture and ownership

This is the engineering map, not a claim that all planned R1 features have shipped. Confirm behavior against the checked-out revision; local application changes can be ahead of committed `dev`.

## Current stable boundaries

| Location | Owns |
| --- | --- |
| `apps/web/src/main.tsx` | Browser workspace, file attachment, settings, conversation orchestration |
| `apps/web/src/api.ts` | HTTP and streaming transport/types |
| `services/api/lab/main.py` | Request validation, topic operations, upload/chat orchestration |
| `services/api/lab/parsers.py` | Converter adapters |
| `services/api/lab/models.py` | Local model discovery and inference boundary |
| `services/api/lab/context.py` | Context budget and oldest-input truncation |
| `services/api/lab/storage.py` | Topic paths and persisted records; original preservation |
| `scripts/dev.py` | Development service lifecycle |

Data flows from browser through API orchestration into parser/model/storage boundaries and back. The app's learning material lives outside the code repository in a topic directory. Tests must override those roots. The model does not gain developer shell or filesystem access from these engineering agents.

## Contract direction

Parser-specific objects should be converted at the ingestion boundary into explicit document, chunk, and asset records. Retrieval consumes those records; it should not require the UI to understand a parser library. Conversation records own durable per-answer metadata. Storage owns formats and migration/recovery decisions. API types and their consumers must remain aligned.

Structured ingestion/retrieval work is evolving separately. When it lands, extend this map with its actual files and validated contracts. Do not invent fields here that the implementation does not support.

Keep pure transformations separate from I/O. Framework route and storage classes are existing boundaries, not a reason to distribute mutable business state. Refactor incrementally when a task touches the relevant responsibility.

## Product invariants

- Every retrieval and persistence operation is scoped to an explicit topic.
- User originals are immutable evidence.
- Unknown/failed conversions do not appear ready.
- Model calls respect configured capabilities; unavailable features are not simulated.
- Older prompt input may be truncated; saved history remains. Automatic compaction is deferred.
- Future tools, web access, and hardware execution need separately designed enforcement and authorization.

Architecture changes must state affected contracts, error behavior, persistence compatibility, and a concrete observable check. Detailed coding rules live in `engineering.md`.
