# Pivot to LangGraph

Date: 20 October 2026. Status: [research completed](2026_10_20_langgraph_research.md); design in progress. This is the consolidated planning/decision record requested by Tanmay, not implementation authorization or a claim that LangGraph is already integrated. Baseline: `63d0e84` on `dev`.

## Decision and learning objective

LangGraph is a required R1 learning and architecture objective. The coordinator's earlier recommendation to defer it in favor of custom orchestration is superseded by Tanmay's explicit correction on 20 October. Preserve the [earlier discussion](../evidence-retrieval/2026_10_15_evidence_retrieval_discussion.md) and [implemented workflow record](../evidence-retrieval/2026_10_19_evidence_retrieval_implementation.md) as history; they describe the current implementation, not the target direction.

The pivot must put real workflow transitions under LangGraph rather than wrapping the old orchestrator in one graph node. Independent parsing, retrieval, prompt/context budgeting, local Ollama access, storage and UI modules should remain reusable. Scope and ownership of each workflow, state, context, persistence, streaming, cancellation and future recovery must be settled before code changes. LangGraph does not itself verify model answers, authorize sources or replace the application's domain rules.

## Planning procedure and evidence

Researcher reads current code and verifies primary LangGraph documentation/package contracts. Designer consumes that completed research and maps the migration into small independently testable commits. Coordinator synthesizes both reports here, preserves separate dated research/design records in this folder, explains consequential decisions to Tanmay and checks documentation links before committing. No application code or dependencies are changed during planning. Raw assignments/evidence remain ignored under `.local/verification/reports/langgraph-pivot/`.

The last completed application baseline passed 683 backend tests plus 21 subtests and 236 browser tests, with build/static checks and actual isolated parser/model/browser observations. Those are historical baseline results, not a test of a LangGraph integration. The final plan will state exact compatibility invariants, failure/replay/privacy risks, unresolved questions and validation gates rather than treating framework features as already proven.

## Completed research checkpoint

Research recommends family graphs sharing a runtime boundary, retaining the current direct Ollama gateway and deterministic context planners. It specifically rejects a one-node wrapper around the old orchestrator. Request-scoped graphs come first; durable execution needs its own idempotency, staged-output, freshness and privacy contract. Primary-source inspection identified admission-before-headers, partial-output finalization, unbounded custom streaming, remote-tracing defaults and cross-store checkpoint publication as concrete design gates. These findings and verified-versus-unverified distinctions are preserved in the separate research report. Designer now owns selecting interfaces and small implementation slices; no dependency/runtime spike has run.
