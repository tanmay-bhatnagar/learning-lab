# My proficiency and personalized prerequisites — implementation

Date: 12 October 2026. User authorizes full implementation, testing, isolated end-to-end verification and remote push of completed small checkpoints on dev. Root owns shared Git, integration and durable notes; coder is the sole application/test writer. Use the existing consolidated plan and dated user decisions. A redundant designer was started to revisit interfaces; after the turn interruption this agent will not be resumed and no new design pass gates implementation.

## Acceptance and sequence

1. Optional structured-output schema through the existing local gateway, preserving ordinary calls; isolated synthetic selected-model compatibility/quality probe.
2. Shared CV storage/configuration outside topics, exact chosen original filenames, collision rejection/rename-before-upload, ordinary parsing and complete extracted text with immutable originals.
3. Versioned My proficiency JSON with user-added/editable concepts, per-requirement self-reports and deterministic compact context; manual entries survive regenerated proposals.
4. CV-gated on-demand high/medium prerequisites using fresh policy, complete selected-section/CV evidence, validation before actionable cards and request-bound lifecycle.
5. Latest compact learner/plan context on learning chat; optional Always include CV supplies complete extracted text each turn, never retrieval chunks or silent trimming.
6. My proficiency, CV upload/preview, per-requirement questions and context controls in the browser, with typed boundaries and shared activity/lifecycle guards.
7. Explicit captured-destination main-chat handoff and plan/answer state, no side chat, automatic sends or per-answer model calls.
8. Independent review, full automated gates and isolated real Docling/Ollama/browser end-to-end tests, then remote dev push and verification.

Each meaningful reproduction/implementation/test-loop/repair/documentation checkpoint is committed locally, including failing intermediate states. A piece must pass its relevant checks/repairs before the next dependent piece. No one-shot feature commit, squashing of failure evidence, or silent weakening of tests. No personal topic/CV or downloaded model enters verification. Raw evidence stays ignored.

## Gateway reproduction checkpoint

Coder (Luna Medium) added two scoped gateway tests: schema mapped to Ollama format and visible schema-stream error without done. `PYTHONPATH=services/api .venv/bin/pytest services/api/tests/test_models.py -q`: two failed,17 passed plus13 subtests, because the existing gateway rejects response_schema. Earlier invocation without PYTHONPATH failed collection; corrected invocation separates that setup error from the feature gap.

Existing research plus [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) supports an optional keyword on the existing gateway over prompt-only JSON or a second adapter: it preserves local-model checks, shared lock, budget and cancellation. Format must be omitted when no schema is requested. Fake-HTTP tests verify payload/error behavior, not actual selected-model output quality. Root owns the later synthetic real-model probe; coder implements the narrow seam after this failing checkpoint is committed. No further design-agent pass is required.

## Gateway and installed-model checkpoint

Failing reproduction: e50ed3e. Optional-format implementation: 2acb526. Coordinator reran `PYTHONPATH=services/api .venv/bin/pytest services/api/tests/test_models.py services/api/tests/test_models_multimodal.py -q`: 30 passed and 21 subtests passed. Coder also reported scoped Ruff/format and engineering checks passing. This changes only an optional gateway keyword; ordinary callers remain unchanged. A second adapter or separate model would duplicate locality/lock/budget/cancellation behavior, so the documented existing Ollama format seam remains the selected branch.

Coordinator used installed `qwen3.5:4b-q8_0`, Thinking off, 8,192 context with synthetic runtime policy, short synthetic CV and maximum-likelihood/gradient-descent section. Both real calls completed and returned parseable schema-shaped JSON. First prompt used unrestricted string references: the model shortened `section:1` to `1` and speculated about calculus exposure from introductory statistics. This demonstrates that JSON shape is insufficient provenance/knowledge validation. Second probe used enumerated exact source IDs and explicitly required unstated background to remain unknown. It returned exact references and no unsupported CV evidence. Use allowed-ID enums plus server validation and unknown-versus-mentioned CV evidence; self-report still has an independent question for EVERY requirement. No textual background assessment may silently establish mastery.

The probe supports proceeding with the existing gateway; it does not establish prerequisite usefulness across documents, PDF fidelity, longer prompts, or Thinking-on completeness. The second answer was narrower, which needs broader synthetic scenarios in final usage validation. Source-reference membership is a structural guarantee, not proof that the requirement is semantically justified. Conditions for revisiting: recurring semantic/format failures across the implemented prompt, model/daemon incompatibility or incomplete responses. Owner: coordinator/tester with coder repairs. Raw synthetic messages/events are ignored under `.local/verification/proficiency-schema-spike/`; no personal data or new model downloads were used.

## Shared-profile boundary checkpoint

Proceed from the saved consolidated plan and dated user choices; no second design pass is needed. Root coordinates remaining technical interfaces. Coder owns storage/config tests and implementation; root owns Git/docs. Default profile root is the sibling `Profile/`; explicit injection/environment configuration and verification/test fixtures isolate it. Prefer a normal configuration seam plus test fixture override over production test-only branching or deriving ambiguous profile paths from arbitrary temporary topic roots. CV originals retain exact chosen names; separate internal IDs permit metadata/derived revisions without renaming originals. Atomic exclusive publication plus a root-scoped file-lock boundary protects normalized-name collisions across processes, rather than relying only on the application's in-memory lock. This boundary will be exercised with synthetic storage tests before any live API verification. Parser/router integration remains a later dependent slice.
