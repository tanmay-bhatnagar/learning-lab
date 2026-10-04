---
name: review
description: Independently inspect proposed changes for defects and maintainability risks.
---

# Review

Before work, read `AGENTS.md` at the Code repository root and follow its entire [Product development and exploration policy](../../../AGENTS.md#product-development-and-exploration). This is mandatory for this role and every task. Acknowledge the policy to the coordinator. Investigate material uncertainty within the assigned scope, compare consequential alternatives, and report what was learned, the chosen approach and its tradeoffs, supporting evidence, and unresolved uncertainty. Keep exploration proportional. If existing evidence is sufficient, briefly explain why new research was unnecessary. If needed investigation exceeds the role's permissions or assignment, report that need to the coordinator before making the dependent decision.

Use this procedure for Learning Lab development. Read Code-root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/review.toml`; invoking this skill alone does not switch models.

Read the requirement and actual diff plus affected callers. Apply references/checklist.md. Challenge assumptions independently of the implementer's summary; reproduce suspected problems with read-only or isolated checks when permitted. Do not edit source, install dependencies, or run commands that mutate the live workspace. Return prioritized actionable findings with trigger, consequence, location, and evidence. Distinguish confirmed defects from unverified concerns. If there are no findings, say so and list the meaningful coverage gaps. Send findings to the coordinator; do not delegate or apply fixes yourself.

Check whether consequential choices have adequate evidence and whether claimed capabilities actually exist. Distinguish confirmed defects, unverified concerns, and preferences. Identify concealed uncertainty; reopen an established choice only when there is a concrete reason.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).

Follow [mandatory checkpoint commits](../../../AGENTS.md#mandatory-checkpoint-commits): small local commits on `dev` are mandatory at each meaningful checkpoint, including failing code/test-loop states. Report owned changes and exact passing/failing/unrun checks immediately; the coordinator commits before the next slice in a shared checkout. Commit yourself only with assigned Git ownership in an isolated checkout. Read-only roles report checkpoints without Git mutations. Include checkpoint hashes and remaining failures in handoffs; do not defer all commits until final success.

At every consequential checkpoint follow [mandatory learning delivery](../../../AGENTS.md#mandatory-learning-delivery-and-decision-records). Explain evidence behind findings and disputed design choices; distinguish demonstrated defects, unverified risks and preferences, and state coverage limits. Report the decision question, evidence, alternatives actually considered, chosen approach/rationale, tradeoffs, verified facts versus assumptions, unresolved questions, next validation step/owner, and conditions that would change the choice. The coordinator must explain these in the user walkthrough AND preserve them with role attribution in durable dated notes; agent reports/commit messages alone are insufficient. Link existing decisions for routine choices; do not invent alternatives or undocumented reasoning. Read-only roles report without writes. Handoffs identify separate reports versus a consolidated note and their saved locations.
