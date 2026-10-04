---
name: design
description: Plan behavior, data contracts, and component ownership before implementation.
---

# Design

Before work, read `AGENTS.md` at the Code repository root and follow its entire [Product development and exploration policy](../../../AGENTS.md#product-development-and-exploration). This is mandatory for this role and every task. Acknowledge the policy to the coordinator. Investigate material uncertainty within the assigned scope, compare consequential alternatives, and report what was learned, the chosen approach and its tradeoffs, supporting evidence, and unresolved uncertainty. Keep exploration proportional. If existing evidence is sufficient, briefly explain why new research was unnecessary. If needed investigation exceeds the role's permissions or assignment, report that need to the coordinator before making the dependent decision.

Use this procedure for Learning Lab development. Read Code-root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/design.toml`; invoking this skill alone does not switch models.

Trace the current caller and data flow. Define observable acceptance criteria, input/output shapes, owners, error states, persistence compatibility, and verification. Compare alternatives when the choice has meaningful consequences; do not require multiple prototypes for routine work. Prefer composition and cohesive modules with a small public interface. Keep I/O boundaries explicit. Return a concise design, implementation slices with disjoint ownership where possible, and unresolved decisions. Do not modify application code or create speculative scaffolding.

Explain the intended learner-facing behavior and consequential alternatives. Consider product reliability, maintainability, and Tanmay's learning value. Where useful, propose a small, reversible increment that tests the uncertain part. Identify assumptions requiring investigation before implementation.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).

Follow [mandatory checkpoint commits](../../../AGENTS.md#mandatory-checkpoint-commits): small local commits on `dev` are mandatory at each meaningful checkpoint, including failing code/test-loop states. Report owned changes and exact passing/failing/unrun checks immediately; the coordinator commits before the next slice in a shared checkout. Commit yourself only with assigned Git ownership in an isolated checkout. Read-only roles report checkpoints without Git mutations. Include checkpoint hashes and remaining failures in handoffs; do not defer all commits until final success.
