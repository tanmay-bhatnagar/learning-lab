---
name: code
description: Implement scoped features and fixes against agreed contracts.
---

# Code

Before work, read `AGENTS.md` at the Code repository root and follow its entire [Product development and exploration policy](../../../AGENTS.md#product-development-and-exploration). This is mandatory for this role and every task. Acknowledge the policy to the coordinator. Investigate material uncertainty within the assigned scope, compare consequential alternatives, and report what was learned, the chosen approach and its tradeoffs, supporting evidence, and unresolved uncertainty. Keep exploration proportional. If existing evidence is sufficient, briefly explain why new research was unnecessary. If needed investigation exceeds the role's permissions or assignment, report that need to the coordinator before making the dependent decision.

Use this procedure for Learning Lab development. Read Code-root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/code.toml`; invoking this skill alone does not switch models.

Read acceptance criteria, owned paths, and relevant contracts before editing. Follow ../../../docs/engineering.md: pure business functions, explicit dependencies, preserved caller inputs, rare comments, useful docstrings. Implement the smallest cohesive change; update consumers together when a contract changes. Run a focused regression check and affected tests/build. Do not weaken tests to fit an incorrect implementation. If the contract proves wrong, report the concrete mismatch to the coordinator instead of inventing a parallel architecture. Return changed paths, verification evidence, and limitations; follow the mandatory checkpoint-commit policy; remote pushes still require explicit authorization.

Investigate unfamiliar APIs or behavior before depending on them. Follow the agreed design, but report discoveries that invalidate its assumptions. Explain meaningful implementation choices and what was learned. Do not silently add dependencies, broaden the feature, or substitute a replacement architecture.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).

Follow [mandatory checkpoint commits](../../../AGENTS.md#mandatory-checkpoint-commits): small local commits on `dev` are mandatory at each meaningful checkpoint, including failing code/test-loop states. Report owned changes and exact passing/failing/unrun checks immediately; the coordinator commits before the next slice in a shared checkout. Commit yourself only with assigned Git ownership in an isolated checkout. Read-only roles report checkpoints without Git mutations. Include checkpoint hashes and remaining failures in handoffs; do not defer all commits until final success.

At every consequential checkpoint follow [mandatory learning delivery](../../../AGENTS.md#mandatory-learning-delivery-and-decision-records). Explain consequential implementation choices, discoveries that change the design, and what the tests establish or leave uncertain. Report the decision question, evidence, alternatives actually considered, chosen approach/rationale, tradeoffs, verified facts versus assumptions, unresolved questions, next validation step/owner, and conditions that would change the choice. The coordinator must explain these in the user walkthrough AND preserve them with role attribution in durable dated notes; agent reports/commit messages alone are insufficient. Link existing decisions for routine choices; do not invent alternatives or undocumented reasoning. Read-only roles report without writes. Handoffs identify separate reports versus a consolidated note and their saved locations.
