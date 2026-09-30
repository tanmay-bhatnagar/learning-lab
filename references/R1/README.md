# R1 current state

Snapshot after `dev` commit `b2a6b71` (30 September 2026). The [interactive system map](system-map.html) has two layers; select a block to see its components. [Editable diagram source](system-map.fragment.html). The full ordered plan remains in [R1.md](../../../R1.md).

## Built

- Topic-scoped browser workspace: PDF upload and viewer, attached files, settings, local model and reasoning controls, saved chat, context meter.
- Docling ingestion: structured text, Markdown, provenance, page and figure images, bounded chunks. MarkItDown and AnyDoc remain Markdown alternatives.
- Topic SQLite keyword and embedding index, ranked retrieval, trace view, and per-answer citations that survive reload. Chat uses one retrieval pass before streaming a local Ollama response.
- Request-local context trimming preserves durable history. The five reviewed ingestion and retrieval bugs were fixed; missing indexed evidence and unfit prompts now fail visibly.
- Project engineering rules, six role configurations and skills, CI, synthetic tests, and an isolated HTTP verification helper.

## R1 still to build

| Order | Work |
| --- | --- |
| 1 | Open cited PDF pages; add a learning goal to each topic; flag content the parser could not extract faithfully. |
| 2 | Multiple saved conversations per topic; per-turn trace and retrieval evaluation baseline. |
| 3 | Document outline, section summaries and material map. |
| 4 | LangGraph workflow, retrieval tools, tool-call validation and scoped approvals. |
| 5 | Understanding checks, topic progress memory and restart recovery. |
| 6 | Full R1 acceptance demonstration, then context compaction. |

The functional-programming refactor is a separate engineering pass before adding agent workflow complexity. Coding experiments, web research, full multimodal support and Jetson hosting belong to later releases. The 107-PDF parser comparison remains deferred until Tanmay explicitly requests it.

## Validation at this snapshot

- 128 Python tests and 17 frontend tests passed. Production web build, Ruff and engineering configuration checks passed. GitHub CI passed on `b2a6b71`.
- Isolated real HTTP upload/conversion/persistence passed with MarkItDown and a synthetic PDF; original bytes were preserved.
- Retrieval and citation integration tests exercised the actual model adapter with mocked HTTP. Independent review caught a whitespace regression in oversized code chunks; it was fixed and re-reviewed without further findings.
- The current Docling path has targeted unit and synthetic integration tests. This snapshot does not certify real-model answer quality, the full browser chat journey after the latest changes, difficult PDF extraction quality, or the full parser corpus.

Sources: [architecture](../../docs/architecture.md), [API contract](../../docs/API.md), [validation history](../../docs/validation.md), and the committed tests. Local bug-fix evidence is retained under ignored `.local/reviews/` and `.local/verification/`; it contains no personal topic data.
