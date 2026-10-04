# Document map implementation and learning checkpoints

Implementation approved by Tanmay on 5 October 2026. Base: `d477619` on `dev`. The [regenerated plan](2026_10_05_document_map_plan_regenerated.md) and [original plan](2026_10_05_document_map_plan.md) remain preserved design history.

The coordinator owns shared-checkout Git and this consolidated implementation/decision record. Code uses the configured Luna Medium role, review Sol High, usage Luna Medium. All workers read Code-root policies and their skills. Five implementation slices are sequential; each is verified and reviewed before dependent work. Failing-test and repair checkpoints receive additional local commits when needed rather than being hidden in five large commits. Remote publication is not authorized.

## Accepted integration decisions

- Native structured source is the map authority. Existing flat headings stay flat; no default parser change or automatic reparse. Coverage refers to extracted content, not certified PDF fidelity.
- The same local model gateway receives a fresh full-policy/section/task prompt; chat history and topic goal do not enter summaries. Existing inference lock serializes work and current `keep_alive: 0` is preserved.
- First version refuses oversized complete-source requests before model generation; no source trimming/top-k substitution.
- Add to main chat names the currently selected existing conversation, imports a saved immutable summary snapshot with source/provenance metadata, and creates neither a model call nor a side chat. This selects the design recommendation as a routine integration decision within the user's implementation approval. Import schema/idempotency must be verified before slice 5 completion.
- Pure source, prompt/attempt and import transformations remain separate from storage/HTTP/model effects and frontend hooks/components, making each responsibility inspectable.

## Slice 1 — source reconstruction

Completed source contract at `37e7950`, cleared by independent bounded review (12 focused tests passed); real artifacts remain a later usage gate. Code owns the pure source/outline module and focused synthetic tests. The initial question is whether ordered source units can preserve repeated headings, parent introductions, preamble, tables/captions/formulas and multipage/unlocated content. Native traversal was selected over chunk grouping because chunks drop occurrence identity. The cost is explicit serialization/accounting; the validation gate is complete extracted-source allocation without duplicate parent prompt units.

## Remaining checkpoints

2. Versioned map storage and outline API: explicit build/read/rebuild, isolation/staleness/corruption/idempotency.
3. Interactive Map navigation: backend-validated schemas, independent file selection, page links and accessible honest outlines; no model calls during navigation.
4. Full-source summary backend: fresh policy, fit preflight, request-bound streaming, lock cleanup, provenance, complete-versus-incomplete durability and recovery.
5. Summary controls and main-chat import: Generate/Stop/Retry/Regenerate, saved reuse, race protection, idempotent imported snapshots, isolated real browser/model verification.

Application completion and real usage remain unverified until these checkpoints finish. This record will be updated with observed test/review results, commit references, decisions and open limitations as work proceeds.

### Slice 1 observed loops and independent review

- `68413a3`: initial synthetic regression checkpoint failed at collection because the module did not exist. API inspection supported native per-item traversal/serialization.
- `5a19cc8`: implementation checkpoint passed two tests and failed an incorrect scaffold expectation for a trailing Unsectioned section. Native trailing material belongs to the current heading.
- `972f700`: serializer/source-validation checkpoint passed three focused tests and failed two fixture/exception-contract expectations. Actual multipage, table, formula and list cases were added.
- Independent Sol High review reproduced parent concluding text wrongly assigned to a nested child, dangling native references escaping as IndexError, nonexistent provenance pages accepted, and furniture absent from accounting. These are repair gates before slice 2, not accepted limitations.

The decision question is whether default native traversal/schema validation alone establishes correct section ownership and source accounting. The experiments showed it does not. Explicit map-level structural/reference/page validation was selected over trusting defaults, with bounded extra validation complexity. Native parent ownership takes precedence where expressed, while ordinary flat body siblings still use semantic heading boundaries. Coverage must distinguish included text, caption aliases, unlocated items and excluded furniture. Source-reconstruction correctness remains unverified until repaired tests and independent recheck pass; code owns repairs, reviewer owns independent recheck.

- `f36012b`: eight focused source tests passed; full backend suite passed 290 tests plus 21 subtests. Further independent probes still reproduced canonical subtree ordering, shared-caption duplication, lost caption-page provenance and BODY-attached furniture accounting bugs. A passing suite did not prove source completeness.
- `09f6dec`: four failing targeted regressions captured those review findings (eight existing cases passed).
- `37e7950`: canonical source-order aggregation, caption provenance union, explicit all-layer furniture exclusions and shared-caption ownership rejection passed 29 focused map/Docling tests plus Ruff/format/engineering. Coordinator reran the 29 focused tests successfully; independent final recheck passed all 12 focused map cases and cleared slice 1.

Conservative validation decisions: positive provenance referring to a missing native page now raises CorruptData rather than warning/unlocated recovery; absent provenance still maps to Unlocated. Shared captions across multiple owners also fail visibly rather than choosing an arbitrary owner. These supersede the permissive fallback proposal: they avoid wrong citations/duplicated source but prevent navigation on those malformed/ambiguous artifacts. Reopen with a recovery design only if legitimate real artifacts regularly encounter these constraints. Synthetic tests establish the chosen contracts, not real-PDF extraction fidelity; API/usage owners must check isolated real artifacts next.

## Slice 2 — outline persistence and API

In progress. Code owns map storage/API boundaries and tests, plus router registration. Explicit POST builds; GET never creates an outline or invokes a model. Revision binds actual original PDF bytes, exact native artifact bytes and builder version, because a source hash alone misses changed extraction. Identical builds preserve saved work; changed extraction is reported stale before an explicit rebuild. The alternative of embedding maps in conversation records was rejected because map ownership is topic/file, not chat. Corrupt saved records must fail visibly rather than masquerade as not built.
