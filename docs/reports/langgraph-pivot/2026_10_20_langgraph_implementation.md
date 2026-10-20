# LangGraph pivot implementation record

Date started: 20 October 2026. Consolidated, coordinator-maintained checkpoint record for implementing the [pivot plan](pivot_to_langgraph.md) with the amendments in the [validation design](2026_10_20_langgraph_validation_design.md). Roles: coordinator (Claude Opus, main session) owns research, design, review, testing, usage, Git and this record. Coding sub-agents implement assigned paths. Raw evidence lives under ignored `.local/verification/reports/langgraph-pivot/`.

## Checkpoints

| Gate | Commits | What changed and what it established | Checks |
| --- | --- | --- | --- |
| 0. Validation | `0349cd1` | Executed research spikes (isolated environment) confirmed the bounded-sink/owned-task runtime with the production `FinalizedStreamingResponse`. They also found four plan gaps: AnyIO shields do not protect node code from LangGraph cancellation; sync callables run in a thread pool; the default recursion limit is 10,007 and environment-controlled; and inherited LangSmith settings upload run data unless `tracing_context(enabled=False)` wraps the invocation. Contracts amended accordingly. | Baseline backend 683 passed + 21 subtests; OpenAPI baseline captured (37 paths). |
| 1. Characterization | `af83e2d` | 24 HTTP-level characterizations (coding sub-agent; coordinator reviewed and reran). They fill gaps the audit found in existing suites: exact event order, terminal messages, persisted effects, call counts and trace outcomes for chat (Default/named, ordinary, opt-in direct/fallback/search/incomplete), summaries and prerequisites. Direct-answer text is asserted by concatenation so fragmentation stays legal. Baseline quirks are pinned, not fixed: summary map drift leaves the attempt `interrupted`; a trace-finalize failure leaves the trace `started` with `assistant_saved=False`; opt-in assistant-save failure is traced as `generation_failed`. | 24 passed on unchanged orchestration. |
| 2. Dependencies | `99c7ca7` | Direct `langgraph>=1.2.16,<1.3` and `langsmith>=0.14.11,<0.15`; lock adds exactly the 21 resolver packages, with no changed pin. | Install with no other version change; `pip check` clean. |
| 3. Channel | `1e219ea` | `EventSink` and `text_fragments`. The coder found that byte slicing with backward scanning mis-split some code points; per-character packing was chosen instead (simpler, verified on multi-byte, emoji and CJK text). | 10 passed. |
| 4. Runtime/lifecycle | `f6da72f` | `invoke_graph` (sole `ainvoke`, tracing off, required limit), `PublishOnce` (`asyncio.shield`), `GraphRun` (getter-safe consumer, terminal after completion), `ActiveRuns` plus app lifespan shutdown. | 9 passed with real graphs. |
| 5. ASGI/privacy | `138f775` | Production `FinalizedStreamingResponse` disconnect matrix (ASGI 2.3/2.4 × middleware × silent/slow/full) finalizes once and releases the lease even when publication raises. Hostile-environment subprocess: 0 connections via `invoke_graph`, while the direct-`ainvoke` control leaks, so the test can detect regression. Coordinator review before product wiring: runtime matches the amended contracts. One hardening item was assigned to gate 6: `events()` must not start a task after `cancel_and_wait()`. | Full backend 741 passed + 21 subtests; engineering, Ruff, format passed. |
| 6. Chat admission | `c41a66d` | Both chat modes and routes admit through an awaited graph: `load_session → select_attachments → (capture_snapshot \| load_context) → initial_retrieval → vision_probe → build_prompt → save_user`. Early trace and lease acquisition stay ahead of the graph with unchanged failure traces. The lease is an injected capability, chosen over importing `lab/web/locks.py` into workflows or moving it now. Old execution consumes the admitted artifacts until gates 7–10; that is staged cutover, not fallback. `GraphRun` no longer starts after `cancel_and_wait`. Review debt: prompt builders/`finalize_trace` are injected from `lab.web.chat` only to keep existing monkeypatch targets; to be removed when those tests migrate (gate 15). | 13 new; full 774 + 21. |
| 7. Ordinary chat execution | gate-7 commit | Ordinary turns run `stream_answer → publish` inside `GraphRun`; `chat_publication.py` owns the single shielded publisher and late-failure terminal. Extra-search still uses the old evidence turn until gate 10. **Deviation from design §runtime:** the ordinary chat sink has capacity 1, not 8. With 8, a fast provider could finish and publish a complete answer before a disconnect was observed, changing the characterized "incomplete on disconnect" outcome. Capacity 1 couples provider progress to ASGI consumption. Coordinator review fix: `cancel_and_wait` waits with `asyncio.wait` and retrieves the task failure instead of `except BaseException: pass`, which also swallowed cancellation of the caller. Gate-6 admission tests now opt into a non-streaming model explicitly (they are gate-6 tests, not characterizations). | 12 new; combined full suite 814 + 21. |
| 8–10. Opt-in chat execution | gates 8–10 commit | `chat_evidence.py`: `evidence_init → decision → (direct_answer \| invalid_prepare → stream_final_answer \| lookup → merge_final_plan → stream_final_answer) → prepare_publication`, recursion limit 12. The opt-in path runs through `GraphRun`; no product code calls `run_evidence_turn`. Its pure helpers are still imported from `lab/evidence_turn.py` until gate 15. **Coordinator review found two defects; both are fixed in the same commit.** (1) Data loss: the first version deferred the complete save behind a cached `PublishOnce` result, so a disconnect on the final token saved no assistant message and left the trace `started`. (2) Gate-7 parity regression in ordinary chat: the same disconnect saved a complete answer and a `completed` trace, where the baseline saves `incomplete` + `cancelled`. Both were reproduced with a probe against baseline `3136086`. **Contract amendment (both chat modes):** the execution graph *prepares* the outcome; exactly one shielded commit in the request path saves it. That commit is complete only when the consumer pulls `done` after graph completion; otherwise `finish()` commits cancelled/incomplete. This preserves the baseline rule that generated content is not proof of delivery. | 12 gate tests + final-token disconnect matrix (ASGI 2.3/2.4 × middleware × ordinary/direct/fallback/search); full suite 844 + 21, run twice. |
| 11. Summary admission | `39fbe26` | `recover_attempts → resolve_map → load_policy → plan_fit → write_generating_attempt`; the lease stays in the HTTP adapter around the awaited graph. Review debt: `ActiveSummary` imported from `lab.web.deps` (backwards layering), fix in gate 12. | Summary suites 28 passed. |
| 12. Summary execution | gate-12 commit | `stream_summary → (validate_and_publish \| publish_failure)` in `GraphRun`; `summary_publication.py` owns success/failure/cancelled publishers; the HTTP module is a thin adapter registering runs with `ActiveRuns`. The gate-11 backwards import is gone (no `lab.web` import under `lab/workflows`). Review debt for gate 15: admission accepts either registration callbacks or the legacy active-summary dict (`_LegacyActiveRegistration`), kept only for older tests. | 11 new; summary suites green. |
| 13. Prerequisite admission | `17e3069` | `recover_and_reconcile → resolve_map → select_cv → load_policy → plan_fit → write_generating_attempt`. Recovery helpers moved verbatim into the workflow module and are reused by the read route. **Sequencing change from plan §8:** plan gate 13 also included buffered generation. Here admission was cut over alone (feeding the existing execution body), and buffered generation moves with validation/publication into gate 14. Reason: admission is independently testable and every cutover remains complete-path, with no partially executed graph. | 11 new; existing prerequisite suites unchanged and green. |
| 14. Prerequisite execution | gate-14 commit | `generate_buffered → check_current_inputs → validate_requirements → register_pending → publish_assessment`, with stream failures routed to `publish_stream_failure`; `prerequisite_publication.py` owns the publishers; the HTTP adapter registers the run with `ActiveRuns`. Recursion limit 8. Review debt for gate 15: `write_prerequisite_attempt` is closure-injected only to keep existing monkeypatch targets. | 14 new; combined full suite 814 + 21. |
| 15a. Summary/prerequisite seams | `b75d110` | Removed the legacy active-summary dict and `_LegacyActiveRegistration`; registration callbacks are now required. Removed the `write_attempt` injections; workflows call the store writers directly, and tests patch the real lookup sites. Kept the clock/ID factories, which have production defaults. Only fixture and monkeypatch wiring changed in older suites; no assertion line changed. | Summary/prerequisite suites 94 passed; full suite green. |
| 15b. Evidence helpers, mechanical | `db965b3` | 18 pure helpers/constants moved verbatim from `lab/evidence_turn.py` to `lab/evidence_result.py`; private names used across modules became public. No other change. | AST proof (local `gate15_ast_proof.py`): 18/18 definitions equivalent after renaming; full suite 844 + 21. |
| 15c. Legacy orchestration removed | gate-15c commit | Deleted `lab/evidence_turn.py` and `tests/test_evidence_turn.py`. Each old test is migrated to `test_workflow_chat_evidence_graph.py` or HTTP opt-in tests; the per-test map is in the coordinator review. Chat prompt-builder and trace-finalizer seams removed: workflows call the owning modules, and a new engineering check plus an AST test forbid any `lab.web` import under `lab/workflows`, including function-level imports. **Review caught a second opt-in regression in the migration:** a final provider stream ending without `done` was recorded as `cancelled` with no client error. Restored to the baseline (`error` event, outcome `error`, trace `incomplete_answer`), and the migrated test was restored to the legacy expectation. Lookup errors again skip the merge; the final chunk IDs are applied only after the final stream opens. **Characterization file:** two approved wiring-only edits (an import path for two message constants; one monkeypatch target, `lab.query_traces.finalize`), with no assertion changed. | Differential HTTP harness (local `optin_parity_harness.py`), 18 opt-in scenarios × baseline `3136086` vs new: 18/18 identical after normalizing timings and random IDs. Full suite 845 + 21. |
| 16. Verification and docs | `d2a6d95`, gate-16 commit | Summary router now declares its destinations, so the compiled topology draws both branches. New [workflow study path](../../workflows.md), with Mermaid transcribed from the compiled graphs; architecture, extra-search, proficiency, R1 snapshot and system map reconciled. | See the completion summary below. |
| 16r1. Chat sequencing out of HTTP | `2abf4e3` | Audit reopen. Extra-search lookup, final source merge/prompt and snapshot revalidation move from closures in `web/chat.py` into `chat_evidence` nodes. New `workflows/chat_stream.py` owns one run handle for both chat modes; the opt-in cancelled-outcome decision moves to `chat_publication`. `web/chat.py` falls from 553 to 138 lines. **Regression fixed:** since gate 10 the search path's trace omitted the lookup's elapsed time from `retrieval_ms`; baseline `63d0e84` included it. | New HTTP test: a slow lookup must appear in `retrieval_ms`; the direct path must not include it. Differential harness 18/18. Backend 847 + 21. |
| 16r2. Test-only helpers removed | `9e8e4d5` | Graph-introspection helpers, forwarding aliases, summary Mermaid wrappers and hand-written prerequisite Mermaid strings leave production code. Topology tests now assert the exact compiled edge sets. The chat ↔ chat_evidence import cycle is gone; an AST test forbids function-level `lab.*` imports in workflows. | Backend 848 + 21. |
| 16r3. Typed boundaries | `9e3c358` | Lines mentioning `Any` in workflows fall from 90 to 22. Boundaries now use `ModelGateway`, `StoreProtocol`, `ProfileStore`, `TopicSettings` and `CloseableAsyncStream`. What remains is imports and `CompiledStateGraph` type parameters, fully open only in the generic graph runners. Review reverted an intermediate change that silenced prerequisite close errors and narrowed summary cleanup handling. | Backend 848 + 21. |
| 16r4. Dead code and lost assertions | 16r4 commit | `ruff.toml` does not select unused-import or unused-variable rules, so a final `--select F401,F841` sweep found four unused imports in workflows, plus 15 findings in pivot tests: unused imports, and locals computed but never used. Three tests computed the workflow error code without asserting it; they now assert `snapshot_changed` or `provider_failed`, matching where `chat_evidence` sets them. The other locals were redundant. The frozen characterization file keeps one unused local. | Backend 848 + 21; web 236. |

## First completion summary (superseded by the gate-16 reopen below)

This first pass declared the pivot complete at `4f5ae29`. The audit in the next section found that declaration premature. Chat (ordinary and opt-in extra search), section summaries and prerequisites run as request-scoped LangGraph admission and execution graphs. `lab/evidence_turn.py` and the legacy orchestration seams are deleted. Nothing under `lab/workflows` imports `lab.web`.

**Verification (coordinator, gate 16).**

- Static and unit checks: engineering check, Ruff (both configurations), Python format, web lint and format, backend 845 passed plus 21 subtests, web 236, production build, and `verify_workspace` (see the final gate run in the gate-16 commit message).
- The OpenAPI schema is byte-identical to the pre-pivot baseline (37 paths).
- Real isolated browser journey (headless Chromium; Docling; `qwen3.5:4b-q8_0`; public Janus-Pro PDF; disposable workspace and synthetic CV). Each step below was observed:
  - upload: 13 pages, hybrid index;
  - ordinary chat with 6 sources;
  - opt-in direct answer, and an opt-in search ("added 3 new passages");
  - Stop: incomplete answer and a cancelled trace;
  - document map built, then the Conclusion summary generated and imported;
  - CV selected, then prerequisites generated.
  - The server log had no 5xx responses, no tracebacks and no LangSmith traffic.
- Timing against baseline `dd9774d` on the same model:
  - Header latency was 0.35–0.44 s on both.
  - With fresh sessions, first-token latency was 7.2–7.9 s on both.
  - Streaming rate was 121–124 chars/s new versus 121–130 baseline.
  - In the sequential same-session runs, the new server's first token was about 0.6 s later. Each new run followed a baseline run, so it had a longer history. That ordering confounds the comparison; it does not show graph overhead.
  - These are single-machine observations, not a benchmark.

**Deviations from the plan.**

- The chat event sink has capacity 1 rather than a larger buffer. This preserves the pre-pivot backpressure on token delivery.
- Chat publication is split into prepare (graph) and commit (request path, on delivery); see gate 7 and the amended contract.
- Two wiring-only edits to the frozen characterization file were approved (gate 15c).

**Regressions caught by review and fixed before push.**

- Final-token disconnect saved a complete answer: gates 7–10.
- Opt-in missing `done` was recorded as cancelled: gate 15c.
- `cancel_and_wait` swallowed caller cancellation: fixed in the gate-7 review.

**Limits.**

- No checkpointer, interrupts, tools, approvals or restart recovery.
- Answer quality and semantic claim support are not assessed.
- The differential harness covers 18 scripted opt-in scenarios, not every provider failure timing.

**Pre-existing defect found during browser use, not caused by the pivot.** Clicking Stop with the mouse before response headers arrive can submit the form again and return `409 topic_busy`.

- How it happens: the aborted fetch rejects first. React then restores the draft and re-renders the same button as `type="submit"`, before the click's activation behavior runs.
- What the user sees: "signal is aborted without reason", and the turn disappears from the UI. The server, meanwhile, has saved the user message and records the turn as cancelled.
- The Vite dev proxy delays headers until about the first token, which widens the window.
- This is left for a separate fix.

## Gate 16 reopened: audit, fixes and acceptance

**Trigger.** Tanmay asked whether the pivot was complete against the plan and the repository's architecture rules. The coordinator compared the code with plan §§2–12, `docs/engineering.md` and Code `AGENTS.md`. That comparison stands in for the gate-16 independent architecture review, which the first pass had not done.

**What already held.** All five model-generation call sites are inside `lab/workflows`, and the old engine is deleted. There is no fallback, switch, checkpointer or tracing. Dependencies are pinned. Summary and prerequisite adapters were already thin. The OpenAPI schema matched.

**Findings that kept the pivot incomplete.**

1. Chat sequencing still lived in `web/chat.py`:
   - opt-in lookup, final-plan building and snapshot revalidation were injected as callbacks;
   - the cancelled-outcome decision was made in HTTP;
   - run and teardown wiring was duplicated.
   This contradicts plan §3 ("nodes own decision, lookup, plan…") and the gate-15 removal of superseded closures.
2. Engineering-rule violations:
   - pervasive `Any` at typed boundaries;
   - test-only helpers and forwarding aliases in production modules;
   - a chat ↔ chat_evidence import cycle hidden behind a lazy import;
   - search warnings defined three times;
   - dead code.
3. Gate-16 acceptance was partial. The browser run missed:
   - named conversations;
   - CV-on/off modes and use of saved proficiency on the next turn;
   - prerequisite familiarity, import and follow-up;
   - reload;
   - Stop during a summary regeneration;
   - concurrent-topic serialization;
   - the plan's synthetic paper and canary CV.
4. The out-of-repository roadmap follow-up required by plan §12 was not recorded (see below).

**Alternatives considered.**

- Correct only the documentation, which leaves the layering wrong.
- Fix the code but skip acceptance.
- Fix everything (chosen by Tanmay): code slices by a sub-agent; review, harness, gates, browser use and docs by the coordinator.

**Fixes.** Slices 16r1–16r3 in the checkpoint table. Each slice was reviewed, tested, committed and pushed separately. Review sent back three problems:

- the circular import and `isinstance` mode dispatch in the first draft of 16r1;
- the summary/prerequisite Mermaid helpers in 16r2;
- the cleanup-semantics changes in 16r3.

**Acceptance, second browser journey** (isolated launcher, headless Chromium, Docling, `qwen3.5:4b-q8_0`). Inputs: the synthetic paper, an unselected control document and a canary CV, generated locally. Evidence is under ignored `gate16b_*` in the local verification folder.

| Check | Observed |
| --- | --- |
| Upload | Both PDFs parsed by Docling with a hybrid index; the paper has 3 pages and 1 visual. |
| Default ordinary chat | "37.4 kelvin … RS-9", quoted and cited to Method p. 1. All 6 sources are from the paper; the control document is absent. The source link returns `application/pdf` at the cited page. |
| Opt-in direct answer | Combined Results (18%) with Method (six-hour baseline), with separate citations. "No follow-up search was made." |
| Named conversation route | Created through the UI; posts to `/conversations/{id}/chat`. Unsupported question (cost): the answer declines. With no document selected, the model invented a description of evidence. Model quality, not pivot. |
| Stop and reload | Partial answer saved and "Response incomplete" shown after reload. Trace `cancelled`, `assistant_saved: true`. |
| Summary Stop | Regeneration stopped after about 1.5 s. Attempt recorded `cancelled` with empty content; the earlier summary is preserved and displayed. |
| Summary import | Snapshot added to the named conversation. |
| CV on | Model returned `CANARY-ZEBRA-4471`. |
| CV off | Model answered "NO CV". This is model self-report only: traces do not record CV inclusion, and the code-level guarantee comes from the existing protected-context and learner-context tests. |
| Prerequisites | Two requirements grounded in Method and in the CV's "No cryogenics or metrology experience". Familiarity answers and a note saved; imported into the named conversation; "Draft a follow-up" filled the composer. |
| Next-turn proficiency | The chat answer matched the saved comfort levels exactly. |
| Concurrent topics, legacy `/chat` route | Topic A streamed 6.3–16.8 s. Topic B's first token came at 20.5 s, after A finished. Both ended with `done`. |
| Server log | 89 successful responses. No 5xx responses, tracebacks or LangSmith traffic. 404s were port probes and one wrong-URL manual request. |

**Not exercised with a real model** (the existing tests use injected faults or saved fixtures):

- the completed-invalid-action fallback, which this model could not be made to produce on demand;
- long-history context fit;
- older stored histories and imports.

**Out-of-repository roadmap follow-up.** `learning_lab/R1.md` sits outside this repository. Its item 7 is unchecked and still says "No LangGraph or LangChain dependency exists". This pass did not edit it. Tanmay should decide whether to mark the LangGraph part of item 7 done and leave retrieval tools, tool-call validation and approvals open.

**Final checks after the reopen.** Recorded in the commit for this record.

## Subsequent independent audit

The separate [independent audit and repairs](2026_10_20_langgraph_audit.md) preserves findings after this implementation record. It resolves the earlier Stop issue and additional metadata, exception disclosure, admission/constructor cleanup, cancellation/publication and generic-typing defects in small red/WIP/repair checkpoints. Final automated evidence is 862 backend tests plus 21 subtests, 238 web tests, all static/build gates and 24 independent closure checks. Actual synthetic local-model/browser verification covers all three workflow families; autonomous search choice and semantic answer/requirement quality remain explicitly limited. Earlier completion/validation entries above remain historical rather than being relabeled with these later counts.
