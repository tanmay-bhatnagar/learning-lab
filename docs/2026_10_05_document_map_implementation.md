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

### Isolated real-artifact source compatibility

Coordinator ran the pure builder read-only on the three existing isolated public-paper native artifacts (Whisper, Janus-Pro, CAVIAR) after slice 1 review. All built without new parsing or model calls. Root sections: 53, 21, 47 respectively (flat headings plus preamble). Source-item accounting was 1239/1239, 258/258 and 554/554. Canonical unit counts were 1210, 240 and 537; exclusions/warnings remain visible. This establishes compatibility with those saved artifact structures, not source-text fidelity, summary quality or full PDF coverage. No personal topic was accessed and no original artifact changed.

### Slice 2 validation discoveries

`667be36` captured six expected failing API/storage cases and one passing topic-scope case before endpoints existed. Independent review later ran 20 focused source/API tests successfully but reproduced accepted corrupt snapshots: wrong file identity returned ready, overlapping section direct ownership abandoned other units, and included/excluded counts contradicted actual units while arithmetic sums matched. It also caught an aggregate-order validator contradicting slice 1, which the writer repaired during review.

The decision is relational validation rather than shape-only deserialization: requested file identity, revision/source self-consistency, unique direct ownership and derived coverage must agree. Extra boundary checks are justified by isolated reproductions; malformed snapshots fail CorruptData, while a valid older snapshot whose actual source changed is stale. Code owns targeted corrupt-record regressions; reviewer must recheck before slice 3.

### Slice 2 completion and UI handoff

`0bd37c2` implements the versioned outline API/storage. Writer passed 37 focused map/API/Docling cases plus Ruff/format/engineering; independent final review passed 20 source/API cases and cleared the three corrupt-snapshot findings. Coordinator ran the full backend suite: 302 passed plus 21 subtests. Real browser interaction remains unverified. Public-paper compatibility evidence above was pure builder execution, not API POST execution; API evidence is synthetic TestClient fixtures.

Identical explicit builds retain state; changed revisions retain historical snapshots rather than silently attaching old summaries to changed IDs. History is not pruned in the first version; this preserves provenance at a disk-growth cost. Reconsider only with an explicit retention contract. Slice 3 starts with an independent Map file picker and explicit build UI; browsing will not invoke generation. Code owns frontend schemas, pure state, hook, components and composition integration; coordinator owns docs.

## Slice 3 — navigation scaffold

Code captured synthetic backend payloads and added two failing integration cases: Map is absent before implementation. The chosen workspace tab and independent file picker preserve conversation attachment selection, at the cost of a separate map read/build lifecycle. Tests require explicit build and expose unsupported parsers rather than auto-converting them. No new external research was needed because the established wire contract and repository composition supply the necessary evidence. Hook cancellation/activity races and real browser navigation remain unverified; code owns implementation and the coordinator/reviewer own verification next.

### Summary/import contract preparation (design role, read-only)

The designer inspected current gateway metadata override, topic lease, streaming finalizer, session projection and map placeholders. These local interfaces support request-bound execution without a new job system; no new external lookup was needed. Slice 4 will validate attempts and completed summaries against exact map revision/source membership, use dedicated started/token/thinking/done/error events with attempt identity, and publish done only after durable completion. Unknown or missing source labels refuse completion; source membership does not establish semantic accuracy. App-owned active attempts and shielded idempotent finalization distinguish live generation from restart interruption. Tradeoff: disconnect ends work; cross-process ownership is outside the current single-process architecture. Code tests persistence/cancellation; review probes races; actual model accuracy remains a usage gate.

Slice 5 chooses additive user-role imported-context metadata over a new role or a simulated assistant reply. Actual content labels the text as generated, so future ordinary chat sees its provenance. Conversation-local atomic session persistence is the idempotency authority; no separate map import registry. Existing exact imports may be acknowledged after a map rebuild, but new imports require a current completed summary. The destination is captured at click time and late responses cannot replace another displayed conversation. Tradeoff: imported text consumes ordinary future context and may be trimmed. Code owns compatibility/idempotency tests; usage verifies named/default destinations and later normal chat. Revisit only if richer imported-context controls or approved background execution require another contract. Designer ran no tests/model/browser calls; these are implementable recommendations accepted by the coordinator, not verified behavior.

### Slice 3 implementation checkpoint `8b98085`

Writer added wire validation, pure file eligibility, workspace-owned hook, recursive navigation and shared build activity. Lint passed and build passed before the latest test edit; focused tests were two passing with one failing protocol-error wording assertion. Browser usage with a real synthetic Docling PDF proved selection did not write a map, explicit Build persisted it, and page links target the isolated original. Coordinator caught preview copy claiming descendant text although the stored preview is direct-only; writer corrected this and added section page links. Neither the browser proof nor passing lint establishes hook race safety. Reviewer/code next validate switched-file/topic requests, stale callbacks and activity cleanup; summaries remain absent.

### Slice 3 stable verification `4e22ba1`

Writer passed 95 tests across 24 web test files, production build, lint, formatting and engineering checks. Five focused integration cases cover explicit build, stale rebuild, malformed response/retry, tab persistence, out-of-order file reads and duplicate build clicks. Cached responses now carry topic/file identity to prevent another PDF's map becoming a fallback. Display distinguishes page groups versus stored heading hierarchy and calls counts extracted-source accounting rather than PDF completeness. Stable isolated browser recheck preserved the picker/outline across tabs and left the chat checkbox unchecked; an earlier picker reset occurred during HMR and was not reproduced. Independent race review is still pending.

### Slice 3 clearance and slice 4 handoff

Independent Sol High review passed five focused cases and found one confirmed protocol defect: section GET may return stale while the browser accepted ready only. `20ea2ea` preserves its failing regression; `bf07d09` fixes the strict union, with six focused tests/build/lint/format/engineering passing. Reviewer cleared the bounded navigation implementation subject to that repair. No arbitrary-status relaxation was used; future statuses need explicit contract updates. Broader keyboard/responsive behavior and summary lifecycle remain later usage gates.

Slice 4 begins under the accepted design contract above. Writer owns pure summary planning/attempt records, persistence, HTTP orchestration and focused backend tests; coordinator owns docs/Git. Full fresh policy and section source plus reserve must fit before creating an attempt or model call. Source labels are validated against supplied units, establishing membership only, not semantic accuracy. Cancellation/save-failure/restart races are required test gates before UI controls.

### Slice 4 test-first checkpoint `30ca771`

Three pure summary regressions initially fail collection because the module is absent. They require full parent/descendant text and fresh policy, conservative whole-prompt refusal, and known source labels. Writer inspected context estimates and metadata override: reusing chat planning would introduce trimming/history/goal, so a dedicated two-message plan was selected. Tradeoff: conservative estimates can reject otherwise feasible source; exact counting is not promised. Backend behavior/cancellation remains unverified until implementation/tests/review. Coordinator prepared a wholly synthetic two-page table PDF under ignored verification storage for the later actual-parser/model usage gate.

### Slice 4 pure-plan checkpoint `fae76cd`

Two tests passed and one scaffold expected two units where the native scope correctly includes four (headings plus text). The writer will assert complete included membership rather than exclude headings to satisfy the test. This strengthens provenance completeness at the cost of extra prompt metadata/tokens. Coordinator also required moving a clock helper from the pure planner into orchestration; timestamps must remain explicit inputs. Marker failures use domain errors. Persistence/provider/cancellation remain unimplemented and unverified at this checkpoint.

### Slice 4 marker repair and real-gateway probe

Independent reviewer found valid [S1] could hide malformed [S0]/[S01]/[SX]. `47e0f60` preserves the failing reproduction; `4787d19` scans all source-like candidates against the exact allowlist and removes clock I/O from the planner. Three pure tests pass. Strict rejection is preferred over partial regex parsing, with a conservative-output-refusal tradeoff.

Coordinator invoked the actual installed Qwen 3.5 4B gateway with fresh synthetic runtime policy and the isolated calibration source. It reached provider done, used [S1] and reported 42, but also described a synthetic-policy detail absent from the document source. This establishes local request/marker compatibility, not summary accuracy or HTTP lifecycle. Writer must explicitly separate policy behavioral guidance from document factual evidence in protected instructions; review will check the prompt, and final usage reruns against the synthetic table document. Stronger instructions mitigate this observed contamination, not enforce semantic entailment. Probe evidence is ignored local JSON; no personal topic/model download was involved.

### Slice 4 API scaffold `071085c`

Three API cases initially fail on the absent route. They protect fresh-policy/source-only prompts and shared generation-lock identity, no-attempt/no-inference overfit refusal, and malformed-marker error persistence. Request model and provider-normalized completed-summary model are distinct provenance facts; legitimate model-tag aliases must not be rejected by stored invariants. Writer owns integration and fault tests next; no completed HTTP summary exists yet.

### Resume after usage interruption — `1168d54`

User resumed after limits reset. Coordinator inspected and preserved interrupted planner/typed-map/summary-store edits before dependent work. Correctly scoped targeted tests passed ten and failed four: three absent summary-route cases and one old map test injecting an arbitrary untyped placeholder. The fixture must become a valid completed summary while preserving same-revision/history assertions; strict stored validation remains selected. An initial coordinator pytest invocation from repository root had import-path collection errors, corrected by using services/api as the working directory. No browser service was left running by the earlier isolated navigation run. Code/reviewer resumed their prior owned roles; router, lifecycle faults and final UI/import remain pending.

### Slice 4 integrated checkpoint `a3c7978`

Nineteen focused source/map/summary API tests pass. Typed records and relational validation bind saved attempts/summaries to revision, section, digest and exact source/page snapshots. Dedicated HTTP streaming uses fresh full-policy/full-source requests and the existing generation lock; last completed output survives failed regeneration. Idle reads recover abandoned attempts under the topic lease. Empty headings remain valid navigation nodes and summary refusal occurs only on request; coordinator's pure probe reproduced the earlier outline rejection, now regressed and repaired. Request/actual model provenance remains distinct.

Writer Ruff and engineering checks pass; five files need formatting. Full backend, cancellation-before-start/wait/running, initial/final save failures, EOF/empty-output and independent relational/lifecycle review remain gates before slice 5. A second actual Qwen 4B direct-gateway probe after the stronger policy-evidence boundary returned only the source calibration fact with [S1] and provider done. This bounded sample supports mitigation but does not certify semantic accuracy or HTTP cleanup. Coordinator is launching a new isolated actual HTTP/table verification run.

### Slice 4 fault checkpoint `929878d` and actual HTTP table run

Writer's full backend suite initially passed 313 tests plus 21 subtests. Independent Sol High review then accepted five self-consistent source/ID records whose matching completed attempt and saved summary disagreed on policy/model/context/thinking/time; the new checkpoint captures these failures. Its sixth failing test is an invalid route-discovery harness under current FastAPI wrappers, not a product cancellation failure. Reviewer supplied the router-endpoint seam and independently proved cancellation before response start, while waiting for the model lock, and after partial tokens: cancelled state persisted, registry cleared and topic/model locks released. Writer must retain these as durable tests and repair pair provenance. Requested versus provider-normalized model tags must be explicitly distinguished, since the current route overwrites request model. Coordinated edits to both policy/model fields cannot be authenticated by pair equality; no such integrity guarantee is claimed.

Coordinator's new isolated actual HTTP run parsed/indexed a wholly synthetic two-page study with installed Docling and local embeddings, explicitly built its flat native heading outline, and generated Methods via installed Qwen 3.5 4B. Provider done and durable summary occurred; the table scores 22/42, equation and high input 20 were retained with known source labels. One low-input clause cited the method paragraph rather than its table support, demonstrating membership validation is not semantic support certification. The UI must retain original source links and generated-summary labeling. Original preservation and final UI/import are later checks. Raw evidence stays ignored under the verification run; stronger provenance changes require a fresh runtime instance before final UI proof.

### Slice 4 repair checkpoint `1a33918`

Twenty-nine focused cases and the full backend suite (325 tests plus 21 subtests) pass, with Ruff check/format and engineering checks. Durable ASGI regressions now cover disconnect before body start, waiting for shared model access and running after tokens; cancelled partial content remains only in attempts, and all locks/registry entries release. Initial/terminal write failures, provider error/EOF, stale revision, malformed/empty labels, abandoned recovery and failed regeneration are covered. Five corrupt-pair regressions reject conflicting same-attempt provenance. Requested model remains attempt.model; optional actual_model records the provider tag, matching summary.model. Older records without that field use their recorded model fallback rather than being invalidated.

The invalid harness expectation was corrected to current Starlette ClientDisconnect behavior. Coherent edits to both fields remain unauthenticated; equality is consistency validation, not tamper-proof storage. Actual table summary retained expected values, but source-label semantic support remains a visible quality limitation. Coordinator verified original PDF bytes unchanged and stopped only the owned isolated services. Final independent recheck and new-runtime UI/model/import remain next gates; writer waits before slice 5.

### Slice 4 clearance and slice 5 assignment

Independent Sol High recheck at `1a33918` passed 31 focused cases and cleared the bounded backend gates without remaining findings. This covers identity/provenance, cleanup/save faults, stale/marker errors and prior-summary preservation. Full backend/static evidence remains writer-attributed. Summary semantic accuracy is not certified.

The final slice now owns typed streaming controls and immutable main-conversation imports under the accepted design above. Existing conversation-local atomic persistence supplies idempotency; no model call or side conversation. Workspace-owned generation survives tab changes and topic/file changes cancel. Server-owned current complete summaries alone can be newly imported, while exact existing historical imports acknowledge retry after rebuild. Required gates are frontend races/decoder/controls, backend import/history compatibility, independent review and isolated actual browser/model flows.

### Slice 5 import scaffold `4f5ae02`

Three synthetic import API tests initially fail on the absent route. They require an existing destination, server-owned summary text, no inference and exact idempotent retry after rebuild. Repository session persistence/history projection supplies the needed evidence; additive metadata is displayed while actual role/content labels enter ordinary future chat context. A second import index was rejected because it would introduce consistency drift beside the conversation's authoritative atomic write. Writer implements backend/import metadata compatibility first, then the final UI controls under the same slice.

### Slice 5 backend import checkpoint `0d4ed0f`

Twenty-two focused import/summary tests pass. Pure snapshot/identity/metadata functions and a thin HTTP route append a server-owned labeled user-context message to an existing conversation, without inference. Topic-locked atomic conversation persistence is the duplicate authority. Message reads and chat validate stored import metadata; history projection excludes display metadata while retaining the generated-content label. Exact prior imports are checked before current-map eligibility so legitimate retry survives rebuild. Named/concurrent/regenerated/stale/incomplete/malformed cases and frontend controls remain gates. Independent review now inspects backend authority/provenance/compatibility; writer retains sole application ownership.

### Slice 5 independent import review and regression `f30fb38`

Reviewer independently passed 22 focused cases but reproduced impossible saved-snapshot metadata (nonpositive pages, duplicate sources, naive/reversed times, empty body and unknown source markers) and an exact-import acknowledgment despite a changed requested section. Nine failing regressions with seven passing cases preserve this evidence. Standalone snapshot invariants and explicit requested-section matching were selected rather than consulting current map state for historical validation; that preserves legitimate retry after rebuild. These checks validate internal consistency, not semantic accuracy or coordinated-edit authenticity. Writer repairs, reviewer rechecks, and later usage verifies named/default/import/reload flows.

### Slice 5 import repair clearance `ef4df3a`

Sixteen import cases and full backend 341 tests plus 21 subtests pass, with Ruff check/format and engineering checks. Independent reviewer reran 35 import/summary cases and repeated the original corruption/replay probes: all contradictions now fail while exact historical retry remains valid. Backend is cleared within those gates. Frontend hook/decoder/controls, imported-message rendering and real browser/model usage remain pending.

### Slice 5 browser wire checkpoint `da9b242`

Three dedicated wire tests and production build pass. The fixture now contains actual synthetic backend started/done attempts, completed summary and import payloads; initial empty-record scaffold was corrected rather than weakening schemas. The decoder handles chunk boundaries, validates events and refuses premature EOF; terminal errors remain explicit events for state/UI handling. Reducer/hook/control and imported-message rendering are next. Independent frontend wire review is beginning; coordinator's fresh isolated workspace has a real Docling table PDF, explicitly built outline and existing named destination ready for final usage. No new summaries have been generated in that final workspace yet.

### Slice 5 terminal-event repair `828800a` → `e827c6f`

Independent wire probe showed one chunk could deliver started/error/done because termination was checked only before the next read. The failing checkpoint also held a mismatched reducer-fixture identity; that was a fixture error, correctly ignored by the reducer. Repair stops current-chunk processing at the first terminal event and adds error→done and done→token coverage. Five wire/reducer tests and production build pass. The decision prevents a later event overwriting terminal state, with request/attempt/scope guards still required in the workspace hook. UI integration and full frontend review/usage remain next gates.

### Resumed final UI integration — 5 October

Coordinator resumed after limits reset without changing the accepted five-slice scope. Code is wiring the final controls and source-linked imported messages. The workspace owns the stream rather than the Map panel: tab changes preserve generation, while topic/file/actual revision changes cancel. A same-file read refresh must preserve the cached outline; briefly clearing its revision would falsely invalidate the running request. Reactive state supplies immediate Stop before the server's started event; controller refs are lifecycle handles, never render state. These are coordinator-identified integration risks under test, not cleared behavior. Code owns deferred-read/tab-switch and stale-callback regressions; independent review and actual browser/model usage remain the next gates.
