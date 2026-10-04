# On-demand document map — research and proposed design

Date: 5 October 2026. Baseline: `2176de4` on `dev`. Status: research/design complete; proposed implementation plan for discussion, not implementation approval. Research and design roles used their configured Sol High and Sol Medium models. Both read Code-root AGENTS.md, their role skills, architecture and engineering, acknowledged the entire exploration policy, and reported evidence and uncertainty. No application changes, personal topics, installations, model calls, or PDF conversions were made during planning.

## Agreed product intent

Map is a dedicated interactive workspace view, not a summary added to chat. Choose a PDF explicitly, build its outline on demand, select a section, and request a summary only when wanted. Saved outlines and completed summaries reopen without model calls. Nothing runs on upload, on opening Map, or for other attached PDFs. Maps belong to topic/file, independently of conversations and chat attachment selection. No new designation of a primary PDF is needed.

The mockup showed a nested outline, page links, summaries and contextual chat. It illustrated interaction, not parser or backend capability. The implementation must correct two assumptions: current extracted headings are usually flat, and chat cannot currently guarantee section-scoped context. Initial Map shows honest detected structure; Ask about this section is a separate later contract.

## Verified research

- `services/api/lab/parse_pipeline.py:175` persists native Docling JSON; body references carry reading order and native items retain occurrence references, heading levels and provenance. `chunking.py:93–101` does not retain those native references in stored chunks. Chunk heading strings cannot distinguish repeated heading occurrences or establish complete section boundaries.
- Installed Docling is 2.127.0 and docling-core 2.98.0. The converter does not enable heading hierarchy enrichment (`docling_pipeline.py:67`). Official documentation describes default PDF level-1 headings. Existing isolated public-paper artifacts have level-1 headings throughout: Whisper 52, Janus 20, CAVIAR 46.
- A synthetic hierarchy/JSON-roundtrip experiment confirmed that item traversal depth is not heading level: sibling body headings with different semantic levels all had traversal depth 1. Use heading.level, not iterator depth.
- Page-filtered iteration selects a whole item when any provenance page matches. Existing isolated parses have multipage items (Whisper 6, Janus 1, CAVIAR 5). Repeated per-page export can duplicate items, while absent-provenance items disappear. Page fallback needs explicit source accounting.
- Numbering-only enrichment on owned deep copies produced nested levels without reparsing in small experiments. This establishes capability, not hierarchy accuracy. The enrichment API mutates its input. Font-style enrichment requires page-cell data not retained in our native saved JSON. Neither form is part of the first implementation.
- Chat prompt budgeting deliberately trims evidence/history (`chat_prompt.py:46–73`, `context.py:37`). A section summary requires a separate full-source planner. Current gateway accepts precomputed context metadata to avoid its default trimming path (`models.py:148`). Counting is conservatively approximate: UTF-8-byte estimate, configured context ceiling 32768, output reserve at most 2048 (`context.py:6–22`).
- Existing topic leases and app-owned model lock can support request-bound summary generation. The gateway has no distinct lock-wait event; the UI must not invent queue position or exact waiting/generation phases.
- Existing query traces are chat-shaped. Summary attempts must be explicitly typed/dedicated; do not manufacture conversation/message metadata for them. Existing retrieval evaluation simulates generation and does not establish summary quality.

Primary sources checked by research:

- [Docling heading levels](https://docling-project.github.io/docling/usage/heading_levels/)
- [Native document representation](https://docling-project.github.io/docling/concepts/docling_document/)
- [Hierarchical and token-bounded chunking](https://docling-project.github.io/docling/concepts/chunking/)

Read-only experiments used synthetic documents and existing isolated public benchmark artifacts; no personal learning topics. The initial synthetic command used an incorrect TableItem import, was corrected, and then passed. Tests/build/browser/model validation were not run for this research-only assignment.

## Proposed learner experience

1. Open Map, select a PDF and click Build outline. Existing structured extraction is read; no model, embeddings, search or automatic reparse is required.
2. See detected sections, nested only when stored heading levels support nesting. Repeated names remain separate occurrences. Without usable headings, see an explicitly labeled Page outline.
3. Select a section to inspect its pages, extracted-content preview, scope and extraction warnings. Navigation stays useful even when summary generation is unavailable.
4. Click Generate summary. Use the selected local model and existing context/reasoning settings. Show Starting summary, streamed output and Stop. No chat history or topic learning goal enters a faithful source summary.
5. Save only a successfully completed summary. Display its source references, model and generation time. Return later without inference. Retry/regeneration is explicit.
6. Overlong material, extraction limitations, invalid sources, failed writes, cancellation and interrupted attempts are visible. No automatic retry or restart generation.

The first release summarizes extracted text, serialized tables, available formula text and captions. Figure page links remain available, but text-only summaries must not imply that visual pixels were understood. Inferred prerequisites, concept graphs, study sequences, whole-paper bulk summaries, LangGraph, durable background jobs and compaction are deferred.

## Source reconstruction contract — spike required

Use ordered native body references and stable occurrence identity under the exact artifact revision. Section boundaries are next equal-or-shallower heading; a parent scope includes descendants, clearly labeled. Canonical source units have one direct owner; parent scopes aggregate child units without duplicating units within a prompt. Preserve parent introductory material, preamble, repeated/empty headings, skipped levels, references and appendices.

For no-heading fallback, allocate a multipage item once to its first valid page group, display its complete page span, and label groups as extracted-item allocation rather than exact page-text crops. Keep unlocated material in a visible separate group. Deduplicate captions owned by tables/pictures; explicitly account for furniture and unsupported serialization.

A coverage manifest must account for every relevant extracted body item as included, unlocated or explicitly excluded. This demonstrates coverage of extracted content, not fidelity against the original PDF. Exact table/formula/list/caption serialization and allocation rules are not settled until the spike passes synthetic fixtures and spot checks of isolated public-paper artifacts.

## Summary, persistence and lifecycle contracts

Build the prompt from complete selected source units in document order, full freshly loaded runtime learning policy, stable source labels, and fixed summary instructions. Treat source content as untrusted evidence. If the full prompt plus output reserve does not fit, refuse before model work with approximate budget guidance. No history/evidence trimming, top-k substitution or silent omissions. A smaller child section or larger supported configured context may help; do not promise either always exists. Multi-pass summarization is a separate later feature.

Validate any generated citation identifier against source units actually supplied. Invalid identifiers cannot produce supported clickable citations. Citation membership does not prove semantic support; real-model quality inspection remains necessary.

Store additive atomic per-file map JSON, schema version 1, within checked topic paths. Missing record means not built; no existing topic/parse migration. Unsupported/corrupt formats fail visibly. Bind map revision to source PDF hash, exact structured-artifact hash and builder/serializer version. Section identity uses native occurrence references, not title text. Stale map blocks new summaries until explicit rebuild; historical summaries must not be reassigned silently. Existing native artifacts remain unchanged.

Keep the last successful summary separate from the latest attempt. Attempts have revision/attempt identity, status, timestamps, source digest, model/settings, prompt/serializer version, policy hash, approximate budget metadata and sanitized error. A saved summary remains a historical output when model, policy or learning goal changes; those inputs are recorded provenance, not permission to regenerate automatically. An explicit regeneration uses current settings. The current model adapter lacks model digest identity; record tag identity honestly until that is extended.

Use the existing topic lease for mutations and summary ownership, and the app model lock for inference. Browsing saved results remains possible. Stop, file/topic switch, unmount or disconnect cancels; switching workspace tabs alone retains the workspace-owned request. Protect terminal writes by attempt and map revision. Closing the iterator must release all resources, including while waiting for model access. Only provider completion, nonempty valid output and successful durable persistence establish a ready summary. Partial/length-exhausted/failed output is incomplete. Failed regeneration preserves the prior successful summary. Persisted generating attempts become interrupted after server restart when no live request owns them; no automatic resume.

Markdown-only parser outputs cannot support native sourced sections/pages. Show unavailable status and an explicit route to the existing Docling conversion/upload flow. There is no reparse endpoint today; do not introduce automatic reparsing.

## Proposed API boundaries

Names remain proposed, subject to contracts checkpoint:

- GET topic/file map: not_built, ready, stale, revision, outline and summary states.
- POST topic/file map: explicitly build/rebuild; idempotent for identical current revision.
- GET map section: metadata, bounded preview with coverage metadata, source pages/warnings and saved summary. Preview bounds must not become summary-input bounds.
- POST section summary: selected model/context/reasoning settings; request-bound stream with terminal persisted status. Stop aborts the stream.

All operations validate topic/file/revision/section membership outside model instructions. Pure source and prompt transformations stay separate from file/database/model effects. Wire schemas follow existing zod and HTTP/domain conventions.

## Implementation checkpoints

Each meaningful code/test checkpoint gets a small mandatory local dev commit, even when its tests fail; commit bodies report passing, failing and unrun checks. Coordinator owns Git in shared checkout. Shared contracts/composition paths have one writer. No remote pushes without explicit authorization.

| Slice | Proposed ownership | Observable acceptance |
| --- | --- | --- |
| 1. Source reconstruction spike/contracts | Pure `lab/document_map.py`, focused synthetic fixtures/tests, this dated design | Full source accounting for repeated/empty/flat/nested headings, parent introduction, preamble, tables, formulas, captions, missing provenance and multipage nodes; resolve serializer choices before dependent work |
| 2. Outline persistence/API | Map storage boundary, `lab/web/document_maps.py`, contracts/schemas/app integration, API docs | Explicit build only; no inference/reparse; topic/file isolation; valid structured artifacts independent of embedding readiness; version/corruption/staleness/idempotency/atomic-write behavior |
| 3. Interactive Map UI | API schemas/URLs, pure map state, `useDocumentMap`, Map components and tab integration | File opt-in, honest flat/nested/page outline, keyboard/mobile navigation, page links/warnings, reload; opening/browsing triggers no generation |
| 4. Summary backend | Pure summary prompt/attempt transitions, HTTP orchestration, focused gateway seams | Full policy, complete-source fit refusal before inference, no trimming, source-label validation, locks, terminal save/failure/cancel/restart, prior summary retained on failed regeneration |
| 5. Summary UI and quality verification | Streaming state, Generate/Stop/Retry/Regenerate, isolated usage evidence | Double-click prevention, independent file states, saved reuse, cancellation races, visible partial output, reload/recovery, factual/support checks on small isolated real-model examples |

Run relevant tests per slice. Completion gates include engineering checker, appropriate backend/web tests, affected web build and lint/format checks. Review and usage roles must independently inspect behavior and operate isolated flows. Include injection/source-isolation fixtures and one table-heavy quality case. Measure actual local latency rather than quote throughput estimates. Full parser-corpus benchmarking is outside this feature.

## Recommendations and remaining uncertainty

Recommend the first release above: honest outline plus summaries that fit one explicit request. Defer hierarchy enrichment until measured accuracy, long-section synthesis until bounded coverage/cancel design, and Ask about section until a validated section-scope chat contract.

Unresolved: native serialization/source allocation fidelity (slice 1), heading enrichment accuracy (deferred), actual summary support/accuracy and generation cost (slice 5), conservative fit refusals, model-tag replacement identity and real cancellation/restart behavior. Planning experiments do not establish production correctness. User discussion/implementation approval remains next; no application implementation has started.
