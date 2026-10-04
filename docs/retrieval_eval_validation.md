# Retrieval evaluation validation — 3 October 2026

The developer retrieval/trace suite lives in [evals/retrieval](../evals/retrieval/README.md); its fast regressions live in [test_retrieval_eval.py](../services/api/tests/test_retrieval_eval.py). The [selection registry](eval_pdf_selection.json) records the original random draw from 107 existing PDFs and Tanmay's reduction to its first three, without a redraw. Original PDFs were read and copied unchanged into isolated workspaces.

## Method and limits

Each PDF was completed separately: inspect original pages, review gold facts and page/row associations, run actual production Docling ingestion and hybrid retrieval, inspect unresolved anchors, then replay a verified index only where source-faithful formatting alternatives were needed. Gold questions and required groups were preserved during these corrections. An unresolved anchor is not silently scored as a retrieval miss.

Runs used installed Docling 2.127.0 and `nomic-embed-text:latest`, 768-dimensional vectors, top-k 6 and context limit 8192. The embedding digest is `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`. Generation emitted fixed simulated text through the production chat route. These runs evaluate source-anchor coverage, retrieval, retained evidence, citations, and query-trace consistency. They do not evaluate answer accuracy, unsupported-question abstention, semantic precision, or overall PDF fidelity. Scores are descriptive; no quality threshold was imposed.

Real parsing and embedding calls used installed local assets. Production retrieval ran once per question; the runner compared its returned evidence with the saved metadata and actual prompt evidence. Parser warning counts do not certify extraction fidelity. No personal Learning topic, model download, publication, or merge was involved.

## Automated checks

After implementation: 262 backend tests and 21 subtests passed; 90 frontend tests passed. Engineering checks, Ruff, Python formatting, frontend formatting/lint, and production build passed. The 19 focused eval regressions passed from both the Code root and API working directory. Build output retained dependency annotation and bundle-size warnings; there were no build errors. Sources: `services/api/tests/test_retrieval_eval.py`, the remaining backend/web tests, and the role verification notes under ignored `.local/verification/`.

## Descriptive baselines

Counts below use required evidence groups, with fixed denominators. Unsupported cases are excluded and retain null retrieval metrics. Indexed availability is source-anchor readiness, not a claim of lossless extraction.

| Paper | Physical pages | Indexed chunks | Answerable / unsupported cases | Indexed groups | Retrieved @6 | Retained groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Whisper | 28 | 240 | 9 / 1 | 40/40 | 32/40 | 29/40 |
| Janus-Pro | 13 | 78 | 7 / 1 | 25/25 | 23/25 | 19/25 |
| CAVIAR | 65 | 141 | 5 / 1 | 11/11 | 10/11 | 8/11 |

Whisper misses all four audio-frontend groups and four of nine Large-v2 training groups. Its robustness-table case retrieves all four groups but retains only one. Janus-Pro retrieves one of three encoder-terminology groups; its training-strategy case retrieves all four groups but retains none. CAVIAR misses the comparative-critic group; its limitations case retrieves all three groups but retains only the long-video module limitation. These remain visible baseline gaps rather than being repaired by relaxing gold facts. Sources: `whisper.v1.json`, `janus.v1.json`, `caviar.v1.json`, and the recorded results below.

All three final runs have no trace/citation/prompt invariant failures or infrastructure hard failures. Across 24 cases, 21 are answerable and three unsupported; all 76 required groups are available in the indexes. Trace lifecycle rejection/cancellation/storage-fault coverage comes from the separate [trace validation](query_traces.md), rather than these successful eval turns.

## Local evidence

Detailed artifacts remain ignored rather than committing copied PDFs, parsed passages, images, histories, or SQLite stores:

- `.local/evals/20261003T153404Z-c0221d10f6/result.v1.json`: final Whisper prepared replay; parser/index came from the initial actual parse. This run predates the final registry/title-only runner adjustment; its recorded source fingerprints identify that revision.
- `.local/evals/20261003T160106Z-b1bb3f3c89/result.v1.json`: final Janus-Pro prepared replay, with current evaluator fingerprints and prior parser provenance recorded separately.
- `.local/evals/20261003T161444Z-0c34605c01/result.v1.json`: final CAVIAR prepared replay; all 11 groups available, with current evaluator fingerprints and inherited parser/index provenance.
- `.local/verification/retrieval-eval-review/review.md`: independent harness, source, association and result review.
- `.local/verification/retrieval-eval-usage/usage.md`: actual runs, source/fingerprint checks and corrections to earlier counts.
- `.local/verification/whisper-eval-design/research.md`, `janus-eval-design/research.md`, and `caviar-eval-design/research.md`: original-page facts, ambiguities and verified formatter corrections.

Runs can be repeated using the commands in the suite README. Prepared replay validates source identity and settings, copies only that topic's original/parser/index assets into a new isolated workspace, and leaves the old run unchanged. Result provenance records PDF/manifest hashes, dirty source-file fingerprints, dependencies and parser/index settings; failures remain explicit.
