# Main-chat evidence requests — design

Date: 15 October 2026. Separate design-role report, filed by the coordinator after [research](2026_10_15_evidence_retrieval_research.md), checkpoint `d257a01`. Proposal for discussion; this report does not authorize implementation. The designer acknowledged the complete development policy/design skill and traced current boundaries. No source, tests, docs or Git were edited by the designer; no installation, inference or additional external research occurred. Root owns filing and checkpoints.

Original findings were returned in `/root/designer2`'s final handoff. A local copy is preserved under ignored `.local/verification/reports/evidence-retrieval/`; the [discussion record](2026_10_15_evidence_retrieval_discussion.md) synthesizes the two separate reports and preserves remaining disagreements/clarifications.

## Recommendation and actual alternatives

Keep initial retrieval. Experiment with one optional additional search requested by the same selected chat model, through a small explicit state machine and existing gateway. Compare deterministic retrieval/retention improvement, a fixed schema decision then answer, and one-round native tool calling. Fixed schema is the provisional smallest experiment, not a production commitment. A multi-round loop has unproven utility and higher cost/complexity. No second routing model, cloud service, SDK or framework installation is proposed.

Deterministic improvements may remove the need for a model decision; fixed schema is inspectable but always uses two chat-generation calls in this proposed variant; native tools may complete without an extra call but require gateway/capability/stream work. LangGraph becomes relevant if durable intermediate resume, longer workflows or external approvals become requirements. It does not supply trustworthy source authorization or fix model judgment.

The coordinator separately proposed a schema answer-or-search union that can return a complete buffered answer in its first call. The designer was asked for a concise clarification on that alternative and effective-input freshness; the addendum below will distinguish it from the fixed-small-decision proposal rather than silently treating all schema approaches as two-call protocols.

## Learner interaction

Proposed per-turn composer option: **Allow one extra document search**, initially off. Off preserves current fast chat. This is a recommendation, not an established user preference or a new persisted conversation setting.

When enabled, show checking for useful additional search, searching selected documents if requested, and preparing answer, then normal final streaming. A compact activity disclosure distinguishes requested, executed and actually retained evidence. Show operation/source provenance, not hidden reasoning or planning JSON.

Stop works throughout. No extra approval ceremony for a registered read operation within explicitly selected documents. No shell, web, arbitrary filesystem, CV or profile tool authority. If no selected indexed documents exist, disable the option with a clear reason; ordinary unindexed-attachment chat still works.

## Proposed protocol

These shapes do not exist in the current application. Exact strict variants:

```json
{"action":"answer"}
```

```json
{"action":"search_selected","query":"Appendix B comparison motivating the selected method"}
```

The model supplies no topic, conversation, path or file IDs. The server captures a nonempty selected-indexed scope. Future file narrowing would need a nonempty subset/membership contract; null/empty must never become unrestricted search.

The app validates completed output, executes the registered search, and constructs a truthful result, conceptually:

```json
{"operation":"search_selected","outcome":"matched","returned_source_ids":["paper:chunk-18","paper:chunk-19"],"new_source_ids":["paper:chunk-19"],"retained_new_source_ids":["paper:chunk-19"],"warning":null}
```

Actual source text accompanies these identities as untrusted evidence; IDs alone are not evidence. The final call explicitly resends complete policy, question, pinned learner context and complete opted-in CV, bounded history, final retained sources and truthful lookup outcome. Same selected weights do not imply automatic memory between calls. Existing hybrid lookup may still use its installed embedding model.

Call counts for this fixed-decision variant: fast mode one generation; opted-in mode two generations whether or not lookup is selected; at most one extra retrieval/embedding. Native may use one generation without lookup or two with lookup. Account for repeated context and existing keep_alive0 unload/load behavior. No timing benefit is measured.

## Module and immutable scope contracts

Capture topic/conversation IDs, selected file identity/hash records, nonempty indexed subset, selected model/think/context/retrieval settings, complete question/history inputs, policy text/hash, effective learner context and relevant versions, optional eligible CV identity/hash/full text, trace ID and explicit mode. Output cannot alter this authority; CV is context, never a searchable document in this operation.

Suggested pure `lab/evidence_request.py`: strict variants, bounded immutable transitions, source deduplication/selection, outcome/diagnostic construction. No HTTP, filesystem, clocks or locks.

Suggested I/O boundary `lab/web/evidence_requests.py`: gateway iterator ownership, read-only retrieval, freshness/status/cancellation/trace effects. Shared chat route retains conversation persistence and topic lease. Existing chat_prompt/context modules own prompt budgets rather than duplicating allocation. Existing schema gateway works for the initial experiment; native tools need an explicit future interface.

States: preflight → initial retrieval → decision → optional lookup → final prompt → answering → completed. Terminal rejected/cancelled/failed records include stage.

Provisional limits to test: two chat-generation calls, one lookup, one action with no arrays/nesting, nonblank query up to500 characters, decision stream up to4KiB, existing bounded retrieval-hit settings, explicit stage timeouts and answer reserve. Limits are app enforcement. Timeout/output values must come from the spike; schema and temperature0 do not guarantee useful output or termination.

## Freshness across effects

A topic lease does not freeze global learner state, CV or policy. Pin a coherent snapshot, then revalidate before subsequent model calls/document operations: valid same policy hash; relevant conversation/learner inputs; selected source identities; and CV eligibility/selection/hash/revocation when inclusion is on. Material change stops visibly and asks for a fresh request, rather than remixing the old decision with new context.

Initial designer wording permits conservative revision rejection of harmless changes. Coordinator asks the clarification below to prefer effective prompt-projection digests and preserve the CV-off no-artifact-read boundary. An unrelated CV change alone should not invalidate CV-off chat. Every subcall carries complete pinned policy; reload/compare policy before later calls. Revocation cannot undo text already sent to an in-flight call but must prevent later reuse.

These are new workflow requirements, not claims of an existing cross-call defect.

## Evidence retention and citations

Deduplicate by stable source identity/content hash and retain initial versus requested stage provenance. Do not compare ranking scores from unrelated queries as one global scale. Explicit deterministic merging should compare baseline allocation with a balanced initial/follow-up allocation in the spike.

Retain/remove complete evidence units. Protect whole question, policy, effective learner context and complete opted-in CV. Optional history/evidence can be removed under existing rules; expose final retained IDs/omitted counts. If all new evidence is dropped, do not claim additional evidence was used. Protected-input overflow visibly refuses.

Current explicit question protection is conditional; characterize/correct the shared boundary if required by this new path. Final citation metadata describes only evidence actually in the final prompt and does not certify semantic support.

First operation uses indexed chunks and existing citation types. Native map units and neighbours remain later operations; map discovery/revision/source representation should not be smuggled into a search-only increment.

## Failures, save boundaries and cancellation

Keep initial preflight before user-message save. Once initial/decision prompts fit and the request is accepted, persist one user turn. Never append planner output/tool requests as ordinary messages.

| Outcome | Recommended behavior |
| --- | --- |
| Valid answer decision | One final answer call from initial retained evidence |
| Search has no match/opening fallback | Explicitly distinguish unmatched fallback from a meaningful match |
| Only duplicate sources | No new-source claim or repeated search |
| New sources omitted by budget | Record omission; answer from actual retained sources |
| Completed malformed/unknown/oversized decision | Execute nothing; visibly skip unavailable extra search and use one baseline answer if preflight remains valid |
| Decision provider failure/missing terminal event | Fail visibly; no hidden generation retry |
| Material context/source/policy change | Conflict; no subsequent inference |
| Unrecoverable storage/index failure | Fail visibly, never disguise as no match |
| Stop/disconnect | Close active work, release owned resources, preserve honest incomplete state |
| Failure after final text begins | Existing incomplete-answer semantics |
| Crash | Unfinished diagnostic state; no automatic resume |

Malformed-output fallback is a recommendation to salvage ordinary chat within the two-call ceiling, distinct from retrying a failed provider. Its visibility is mandatory.

Close/consume the decision iterator before hybrid retrieval takes the shared lock for embedding. Never hold an outer generation lock across both stages. Before final text, incomplete/interrupted assistant status must be honest and compatible with history; preserve save-failure reporting. No new intermediate resume store is needed.

## Trace, history and wire compatibility

Add an optional versioned evidence-request block to per-answer retrieval metadata/query trace JSON. Old records without it remain valid. Suggested fields: mode/protocol version, stage outcomes/times, call/lookup counts, available provider token counters, validated returned/new/retained source IDs and sanitized warning/error kinds.

No prompts, passages, CV text, raw thinking or free-form generated queries in compact diagnostics. Queries can repeat private profile text. Initial disclosure can show operation/scope/outcome/source links; richer query display is a separate product choice.

The existing trace database contains JSON; an optional versioned JSON extension need not require a SQLite migration if readers validate both forms. Do not bump the database version without a storage reason.

Add typed status events only for opted-in requests, preserving ordinary token/thinking/done/error behavior. Browser validates transitions/cancellation/stale responses. Omitted mode retains current API behavior and emits no new stage events.

## Six checkpoints after approval

Each red reproduction, implementation, repair and consequential documentation checkpoint remains a small local commit; six slices do not mean one final feature commit.

1. **Isolated comparison:** current baseline, deterministic allocation/expansion, schema decision and optionally native one-round on same installed selected model/fixtures/policy/budget. Inspect actual answer support/abstention, retention, invalid/redundant actions, calls/tokens and latency. No production rollout.
2. **Pure protocol/source allocation:** strict actions, finite state, captured scope, deduplication, protected-input tests and empty-filter traps.
3. **Backend lifecycle:** shared default/named route, gateway/retrieval, freshness, cancellation/provider close/terminal validation, persistence faults.
4. **Diagnostics/compatibility:** versioned optional records, trace fields/status events, old fixtures, truthful incomplete state, privacy.
5. **UI:** explicit opt-in, progress/Stop, evidence disclosure, unavailable/no-match/degraded states, conversation isolation/stale guards.
6. **Review/real verification:** adversarial scope/document instructions, malformed output, identity/revocation races, context overflow, all-stage cancellation, isolated parser/model/browser proof, required gates and study notes.

Coordinator owns Git/integration; code owns implementation, research/review audits the comparison/architecture, usage proves real flows. Do not rerun design merely to restate the report; reopen only when experiment evidence changes assumptions.

## Acceptance, discussion and uncertainty

Hard gates: captured document scope only; max two generation calls/one extra lookup; no hidden retries/model substitution; no planner JSON completed as answer; complete valid protected context per call; no revoked/stale second-call data; final citation/retention truth; cancellation releases locks/lease/provider; ordinary chat/old histories compatible.

Agree support/latency acceptance before experimenting. Existing evidence supports no invented percentage improvement. Questions for Tanmay: per-turn opt-in first? Is added delay acceptable on hard questions while ordinary chat stays fast? Should free-form search queries eventually be visible, or is operation/source provenance enough?

Verified: existing route/gateway/lock/source/budget/trace boundaries. Unverified: useful action selection, model/quantization reliability, supported-answer benefit, allocation balance, native streaming behavior, real load/token/latency costs and timeout values. Equivalent deterministic results favor cheaper retrieval; reliable cheaper native calls favor native protocol; discarded support favors allocation repair; measured missing dependencies may justify another bounded operation; durable intermediate resume may justify LangGraph.

Checks: read-only tracing/research synthesis. Application tests/build, inference and browser experiments were not run. Application implementation is pending discussion and explicit authorization.
