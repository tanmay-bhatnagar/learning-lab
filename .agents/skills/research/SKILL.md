---
name: research
description: Investigate code behavior and technical options with primary-source evidence.
---

# Research

Before work, read `AGENTS.md` at the Code repository root and follow its entire [Product development and exploration policy](../../../AGENTS.md#product-development-and-exploration). This is mandatory for this role and every task. Acknowledge the policy to the coordinator. Investigate material uncertainty within the assigned scope, compare consequential alternatives, and report what was learned, the chosen approach and its tradeoffs, supporting evidence, and unresolved uncertainty. Keep exploration proportional. If existing evidence is sufficient, briefly explain why new research was unnecessary. If needed investigation exceeds the role's permissions or assignment, report that need to the coordinator before making the dependent decision.

Use this procedure for Learning Lab development. Read Code-root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/research.toml`; invoking this skill alone does not switch models.

Trace the relevant code before external research. Distinguish how it behaves from why it was built that way; infer motivation only when evidence supports it. Check installed versions and primary documentation for uncertain API claims. Compare options against the requested constraints, not feature counts. Return cited facts, uncertainties, recommendation, and any small experiment needed to resolve a decision. Do not edit application code or install dependencies for an investigation without task authorization.

Frame the question or decision being investigated. Compare credible options against the task constraints and separate verified findings, assumptions, recommendations, and remaining uncertainty. The investigation should explain a useful choice rather than merely collect information.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).

Follow [mandatory checkpoint commits](../../../AGENTS.md#mandatory-checkpoint-commits): small local commits on `dev` are mandatory at each meaningful checkpoint, including failing code/test-loop states. Report owned changes and exact passing/failing/unrun checks immediately; the coordinator commits before the next slice in a shared checkout. Commit yourself only with assigned Git ownership in an isolated checkout. Read-only roles report checkpoints without Git mutations. Include checkpoint hashes and remaining failures in handoffs; do not defer all commits until final success.
