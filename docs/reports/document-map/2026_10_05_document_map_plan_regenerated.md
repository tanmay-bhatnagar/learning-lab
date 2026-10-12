# On-demand document map — regenerated research and design report

Date: 5 October 2026. Baseline: `cbbd1d3` on `dev`. Status: regenerated planning report under the updated learning-delivery skills; no feature implementation or implementation approval implied.

**Comparison files:**

- **Original:** [2026_10_05_document_map_plan.md](2026_10_05_document_map_plan.md), containing the first synthesis and its dated follow-up decisions. Preserved byte-for-byte during this regeneration.
- **New:** this file, **2026_10_05_document_map_plan_regenerated.md**, consolidating newly requested research and design contributions under the updated skills.

The original's SHA-256 at regeneration start was `8a0a64098696f3a7b495402eb52215b98958b5a5b22f4780be263f0b5cb9dbb5`. The original plan was first committed as `726bf4e`; updated learning-delivery instructions were committed as `985edd9`; subsequent decision/provenance updates as `cbbd1d3`.

## Report provenance and how to compare

The coordinator reactivated **research** (`document_map_research`, configured Sol High) and **design** (`document_map_design`, configured Sol Medium). Both reread current Code-root AGENTS.md, their updated skills, and the learning-delivery conventions, acknowledging the mandatory policy. They were read-only; the coordinator owns this saved synthesis and commit. There are two regenerated agent contributions in the planning chat and one new consolidated file here; there are no separately saved raw contribution files.

Research checked technical feasibility and evidence; design translated that evidence into behavior, contracts and checkpoints. This report attributes their roles and separates user requirements, verified behavior, reused historical experiments and recommendations. It does not claim that earlier experiments were rerun.

Compared with the original, the organizing unit is now the **decision**: question, evidence, alternatives actually considered, selected branch, rationale, tradeoffs, uncertainty, next validation owner and conditions that would change the choice. The user walkthrough is also required; a saved report or commit message alone cannot fulfill learning delivery. This is an editorial and design improvement, not proof of improved runtime correctness.

## User requirements versus proposed details

**Established by Tanmay:**

- An interactive Map view for an explicitly selected PDF, usually the main paper. Building a map and generating each summary are on demand; uploads, opening Map, section selection and unrelated PDFs do not trigger inference.
- Save completed summaries for reuse inside Map.
- **Add to main chat** transfers a saved summary, section title and source references into an existing conversation. No side conversation, section-specific chat mode or section-only retrieval guarantee.
- Use the same selected local Ollama model; an additional model is too expensive. Separate request inputs must not disturb saved main-chat history.
- Cohesive, inspectable modules that can be studied separately, with explained choices at consequential checkpoints.

**Still recommendations or unresolved contracts:**

- Flat-first outline, page fallback allocation, one complete-source request with visible overfit refusal, request-bound cancellation and additive JSON storage.
- Which existing conversation receives an import, imported-entry schema and idempotency semantics.
- Exact native-source serialization, restart recovery mechanics and source-reference validation.

## Proposed learner flow

Choose a PDF and click **Build outline**. This reads existing structured extraction; it does not reparse the PDF or run a model. Select a detected section to inspect its source pages, extracted-content preview and limitations. Request **Generate summary** when needed; the existing model processes a fresh section-only prompt and streams its output. Stop remains available. Successful output is saved separately from chat and reopened without inference. When wanted, explicitly add the completed summary to the named existing main conversation.

Text, serialized tables, available formula text and captions are the first summary scope. Original-page links remain available for visual inspection. This does not imply that the model inspected figure pixels or that extraction faithfully reproduced every PDF element.

## Decision 1 — authoritative section source

**Question:** Can we build complete sections from existing retrieval chunks or must we use native document structure?

**Evidence and learning — research:** Native Docling JSON is already persisted by [parse_pipeline.py](../../../services/api/lab/parse_pipeline.py). Stored chunks keep heading strings, text and location metadata but drop native occurrence references in [chunking.py](../../../services/api/lab/chunking.py). Research rechecked these paths during regeneration. Earlier synthetic experiments showed traversal depth is not semantic heading level. Repeated heading titles can describe distinct occurrences; string grouping cannot establish complete boundaries. [Native representation reference](https://docling-project.github.io/docling/concepts/docling_document/).

**Alternatives actually considered:** Retrieval chunks/Markdown are convenient but lose identity and structure. Native ordered source references preserve those properties but require serialization and accounting. A model-generated outline costs inference and introduces inferred boundaries.

**Recommended branch — research and design:** Use ordered native body references. IDs combine source occurrence identity and artifact revision; titles are display metadata. A heading subtree ends at the next heading of equal or shallower level. Preserve parent introductory material, preamble, repeated/empty headings, level gaps and trailing references/appendices. Canonical units have one direct owner; a parent scope aggregates descendants without duplicate prompt units.

**Rationale/tradeoff:** Deterministic source identity supports faithful navigation and complete extracted-source accounting without inference. It takes more implementation effort than grouping chunk strings and still proves nothing about material missing from extraction.

**Uncertainty/next owner:** Code, with research support, must prove source boundaries and serializer behavior in the first spike. Review checks every relevant unit is included, unlocated or explicitly excluded. Exact serialization remains a gate, not a settled capability.

**Change condition:** If native serialization cannot preserve essential material safely, revise the source contract and expose the limitation before implementing dependent summaries.

## Decision 2 — honest hierarchy

**Question:** Can the first release show the nested tree in the mockup?

**Evidence and learning — research:** Regeneration rechecked that [docling_pipeline.py](../../../services/api/lab/docling_pipeline.py) leaves hierarchy enrichment disabled. The earlier installed inspection reported Docling 2.127.0/core 2.98.0. Historical isolated public-paper artifacts had all headings at level 1: Whisper 52, Janus 20, CAVIAR 46. Historical numbering-only deep-copy experiments produced nesting, demonstrating capability but not accuracy. These versions/counts/experiments were not freshly rerun. [Heading-level documentation](https://docling-project.github.io/docling/usage/heading_levels/).

**Alternatives actually considered:** Use saved levels honestly; enrich existing JSON from numbering/bookmarks; change ingestion to infer hierarchy, including font style.

**Recommended branch — research and design:** Display a flat detected outline where saved headings are flat. Nest only where stored semantic levels support it. No automatic reparse or guessed subsections.

**Rationale/tradeoff:** Useful navigation can ship without presenting unvalidated relationships as fact, although it will often look flatter than the mockup. Enrichment mutates its input and needs an owned copy; font-style inference depends on page-cell data not retained in current saved artifacts. Changing ingestion would also affect retrieval chunk behavior.

**Uncertainty/next owner:** Code/review validate flat and nested synthetic fixtures. A later research/design exercise can compare inferred hierarchy against manually checked public-paper examples.

**Change condition:** Reliable measured enrichment would justify a separately versioned map-only improvement; the historical feasibility experiment alone is insufficient.

## Decision 3 — fallback and extracted-content coverage

**Question:** What navigation is possible without usable headings, and how do we avoid dropped or duplicated source content?

**Evidence and learning — inherited research:** Docling page-filtered iteration returns whole items matching any provenance page. Historical artifacts contained multipage items: Whisper 6, Janus 1, CAVIAR 5. Per-page export can duplicate them; missing-provenance items can vanish. These observations were not rerun during regeneration.

**Alternatives actually considered:** Repeated per-page export; allocate each source item once and display its full span; refuse mapping when headings are absent.

**Proposed branch — research and design:** An explicitly labeled Page outline. Allocate an item once to its first valid provenance page group while retaining all source pages; keep an Unlocated content bucket. Serialize tables structurally, deduplicate captions owned by tables/pictures and account for unsupported material and furniture. A coverage manifest accounts for every relevant extracted unit.

**Rationale/tradeoff:** Preserves deterministic coverage of extracted items and navigation even without headings. A multipage item under its first page may feel unexpected; groups are not exact page-text crops. Text-only output must not imply visual-pixel understanding.

**Uncertainty/next owner:** Code spike covers multipage tables, missing/invalid provenance, captions, lists and formulas. Usage checks whether page-span labels are understandable. Serializer/allocation details remain proposed until this gate passes.

**Change condition:** Change grouping/display if it confuses users, preserving single ownership and visible coverage. Expose unsupported material rather than silently omitting it.

## Decision 4 — whole-section summary and context limits

**Question:** What does a requested section summary cover, and what happens if that source does not fit?

**Evidence and learning — research:** Rechecked [chat_prompt.py](../../../services/api/lab/chat_prompt.py), [context.py](../../../services/api/lab/context.py) and [models.py](../../../services/api/lab/models.py). Chat planning intentionally trims history/evidence. The gateway can accept precomputed context metadata and bypass that trimming. Counts remain conservatively UTF-8-byte-based, with configured context ceiling 32768 and output reserve at most 2048. Existing retrieval evaluation simulates generation and supplies no summary-quality result.

**Alternatives actually considered:** Reuse top-k retrieval or chat trimming; supply complete source in one bounded request; split source into multiple generation passes and combine results.

**Recommended branch — research and design:** A separate pure summary planner supplies full freshly loaded policy, fixed instructions, stable source labels and every selected source unit. No chat history or learning goal. Preflight source plus output reserve; refuse oversized prompts visibly before inference. Never silently truncate or substitute top-k evidence. Smaller child sections/larger supported context are suggestions only where available.

**Rationale/tradeoff:** The promise of a complete extracted-section summary remains inspectable and bounded. Some useful sections cannot initially be summarized; conservative counts may reject material a precise tokenizer could fit. Multi-pass work adds coverage, intermediate citation, cancellation and quality requirements.

**Uncertainty/next owner:** Code proves no model call on overfit refusal and no source omission on accepted requests. Usage inspects small real summaries for claims, numbers, caveats, omissions and source support, including a table-heavy case. Validate citation IDs against units actually supplied; membership does not prove factual entailment.

**Change condition:** Repeated refusals of useful sections would motivate exact counting or separately designed bounded multi-pass synthesis.

## Decision 5 — same model, independent requests and execution lifecycle

**Question:** How can summaries reuse the local model without carrying or erasing the main conversation's context?

**Evidence and learning — research:** Narrow rechecks of [models.py](../../../services/api/lab/models.py), [chat_session.py](../../../services/api/lab/chat_session.py), [web/deps.py](../../../services/api/lab/web/deps.py) and the budget path confirmed explicit message arrays, the shared inference lock and `keep_alive: 0`. Saved history is projected into each subsequent chat prompt. Research refreshed [Ollama's chat API](https://docs.ollama.com/api/chat), which documents messages and unloading. Design reused that evidence.

**Alternatives actually discussed:** A separate model was explicitly rejected by Tanmay. Fresh requests to the selected model satisfy the requirement. A short keep-alive could reduce reload latency; durable background jobs could outlive browser requests but expand lifecycle infrastructure.

**Recommended branch:** Same selected model, independent prompt messages and serialized inference. Summary context contains policy/source/task; main chat later reconstructs its own prompt from saved history. Keep current unload behavior and request-bound streaming. No autonomous retries, background continuation or added tools. Model weights, saved history and request tokens are different things.

**Rationale/tradeoff:** No additional summary model or parallel application inference is needed. Saved chat remains independent. Current unload behavior may incur reload cost, and request-bound work does not automatically resume after reload. The gateway has no precise lock-wait event; show Starting summary rather than a fabricated queue position.

**Uncertainty/next owner:** Code validates prompt separation, shared locks, policy/source boundaries and iterator cleanup while waiting/running. Usage measures latency, cancellation and unchanged saved history. Actual provider memory behavior needs measurement; the lock alone is not a memory benchmark.

**Change condition:** Alter keep-alive only if measured load latency materially harms interaction and memory remains acceptable. Durable execution requires a separate scope decision.

## Decision 6 — saving, regeneration and recovery

**Question:** What survives failures without becoming mislabeled complete or stale output?

**Evidence and learning — design:** Existing checked topic paths and atomic JSON writes fit additive per-file storage. Source hashes alone miss changed extraction; derived artifact sets are not transactional. Research confirms existing traces are chat-shaped, so summary attempts must not pretend to be chat turns.

**Alternatives actually considered:** Conversation-owned map data; a new job database; additive versioned per-file records.

**Recommended branch:** Per-file map JSON schema v1 within checked topic paths. Revision binds immutable PDF hash, exact structured-artifact hash and builder/serializer version. Missing means not built; unsupported/corrupt data fails visibly. Stale maps block new summaries until explicit rebuild. Preserve historical results without reassigning them silently.

Keep last successful summary separate from latest attempt. Record attempt/revision identity, timestamps, source digest, model/settings, policy hash, prompt version and approximate fit metadata. Only completed nonempty valid output plus a successful durable write establishes ready. Partial/error/length-limited output remains incomplete. Failed regeneration preserves the prior result; abandoned generating attempts become interrupted after restart, with explicit Retry.

**Rationale/tradeoff:** Matches topic/file ownership and avoids coupling to conversations or introducing a broad job framework. Recovery is explicit, and provenance/attempt states add schema detail. Changing model or policy preserves historical output; no automatic regeneration. Model tags lack immutable digest identity in the current adapter.

**Uncertainty/next owner:** Code/review test staleness, late writes, atomic failures, corruption and restart ownership. Usage checks recovery readability. Exact attempt recovery is still a proposed implementation, not verified runtime behavior.

**Change condition:** A requirement for durable execution across disconnects could justify revisiting storage; ordinary individually requested summaries do not yet need it.

## Decision 7 — Add to main chat

**Question:** Where does a saved summary go when Default and named conversations coexist, and how should it be represented?

**Evidence and learning:** Tanmay's Add to main chat decision superseded the initial Ask about this section deferral. Current [storage.py](../../../services/api/lab/storage.py) supports independent conversations; [chat_session.py](../../../services/api/lab/chat_session.py) projects saved history. Existing retrieval metadata describes supplied evidence rather than imported generated summaries. Design proposed destination and representation details; research identified their compatibility/validation needs.

**Alternatives actually considered:** Always send to Default versus the currently selected existing conversation; import as an assistant reply versus a user-initiated generated-context entry. Side/section-specific chat is outside the agreed scope.

**Design recommendation, not user-approved detail:** Name the currently selected destination on the button, Add to “[conversation title]”. Import an immutable snapshot labeled Saved section summary, preserving title, source links and original model/time. Represent it as user-initiated context with additive validated metadata; do not fake a new model answer, verbatim source evidence or retrieval trace. Use server-side idempotency for the same summary version/destination; regenerated versions are distinct.

**Rationale/tradeoff:** Keeps the user in the conversation they are using and makes the destination visible. Imported generated text consumes later context and can be trimmed as history; the durable snapshot remains available even if Map changes. This action requires no inference or new conversation, but does require a new validated persistence contract.

**Uncertainty/next owner:** Coordinator presents destination/representation as recommendations. Design/code settle wire/storage compatibility before implementing; usage checks Default/named destination, repeated clicks, reload, citations and normal subsequent chat. Reject partial/stale results as complete current imports. The exact message role/schema is not finalized by this report.

**Change condition:** Tanmay's preference for Default changes destination. A future request for genuine section-only chat reopens a separate source-selection contract.

## Cohesive modules for studying implementation

Research/design recommend real responsibilities, not a wrapper framework:

| Part | Pure decisions to study | I/O boundary |
| --- | --- | --- |
| Document map | Ordered source units, section IDs/boundaries, coverage, fallback, revision comparisons | Native artifact loading and versioned map persistence |
| Section summarization | Full-source prompt, fit refusal, citation membership, attempt transitions | Existing Ollama gateway and streamed persistence |
| Main-chat import | Snapshot eligibility, destination/idempotency decisions, session transition | Existing conversation storage and import endpoint |
| Frontend Map | Selection/activity/stream transitions and display rules | API hook with cancellation, presentational components |

The fresh-message-list capability already exists in the gateway. Reuse it; do not create another model service. Effects remain in hooks/boundaries and shared schemas/composition paths have one writer. Proposed filenames/API details settle with contracts, rather than speculative scaffolding now.

## Implementation checkpoints and learning delivery

| Checkpoint | Owner/scope | Acceptance and evidence before dependent work |
| --- | --- | --- |
| Source spike/contracts | Code with research support; pure document-map transforms/fixtures | Account for repeated/empty/nested/flat headings, preamble/parent introductions, captions/tables/formulas/lists, multipage and unlocated items; settle serializer/allocation choices |
| Outline persistence/API | Code; map boundary/router/contracts/docs | Explicit builds, topic/file isolation, versions/corruption/staleness/idempotency, atomic failures; no inference/reparse; independent of embedding readiness |
| Map navigation | Code; wire schemas, pure state, hook and components | Honest structure, file opt-in, source links, keyboard/mobile/reload; no generation on opening/browsing |
| Summary backend | Code; prompt/attempt transformations and thin orchestration | Full fresh policy and complete source, no history/trimming, preflight refusal, serialized local inference, citation membership, terminal save/failure/cancel/restart |
| Summary controls/import | Code; UI transitions and validated conversation import | Generate/Stop/Retry/Regenerate, saved reuse, explicit destination, durable/idempotent import without inference, visible incomplete results |
| Independent review/usage | Read-only review; isolated usage | Real-model support/coverage and latency, table-heavy case, policy/injection/isolation, waiting/running cancellation, restart/import/reload flows |

At each consequential checkpoint the coordinator explains what was learned, actual alternatives, evidence-backed selection, tradeoffs, assumptions, next validation owner and change conditions **in the walkthrough and durable notes**. Attribute worker findings and preserve superseded choices. Each meaningful tracked checkpoint gets a small local dev commit even with failing intermediate tests, recording exact passing/failing/unrun checks; required completion gates still apply. No remote push without authorization.

## Verification inventory and open gates

**Performed for this regeneration:** both roles reread current policy/skills and prior plan; research narrowly checked source/adapter/locks/history/budget paths and refreshed official Ollama documentation; design reused those findings and existing verified architecture. Coordinator synthesized this new file, checked engineering/doc links and staged whitespace, and compared the original's hash.

**Inherited, not rerun:** parser version inspection, synthetic hierarchy/roundtrip and numbering enrichment experiments, public-paper heading/multipage counts. Original evidence and limitations remain in the comparison file. No current extraction/model quality result is claimed from them.

**Not run:** application tests/build/lint/format, browser flows, real-model generation, new parsing, expensive benchmark evaluation, cancellation/restart experiments. No application code changed. Read-only roles made no writes or commits; coordinator owns this checkpoint.

Open gates remain native source serialization/allocation fidelity, actual summary support/coverage/cost, conservative fit refusals, provider cleanup, restart behavior, model-tag identity and main-chat import compatibility. The report explains a proposed path; those gates require implementation evidence rather than stronger prose.
