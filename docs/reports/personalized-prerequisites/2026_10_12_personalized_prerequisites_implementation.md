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
