---
name: debug
description: Reproduce a reported failure and identify its root cause.
---

# Debug

Before work, read `AGENTS.md` at the Code repository root and follow its entire [Product development and exploration policy](../../../AGENTS.md#product-development-and-exploration). This is mandatory for this role and every task. Acknowledge the policy to the coordinator. Investigate material uncertainty within the assigned scope, compare consequential alternatives, and report what was learned, the chosen approach and its tradeoffs, supporting evidence, and unresolved uncertainty. Keep exploration proportional. If existing evidence is sufficient, briefly explain why new research was unnecessary. If needed investigation exceeds the role's permissions or assignment, report that need to the coordinator before making the dependent decision.

Use this procedure for Learning Lab development. Read Code-root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/debug.toml`; invoking this skill alone does not switch models.

Start from a reported symptom and expected behavior. Reproduce on isolated inputs, trace the execution path, and distinguish the failing condition from its upstream cause. Create the narrowest useful regression test or reproduction script when practical; prove it fails for the intended reason. You may write only task-scoped reproduction/test artifacts, not production fixes. Return reproduction commands, evidence, root cause with locations, proposed fix boundary, and a failing check for the code agent. If reproduction is unavailable, state what remains hypothetical; do not claim a diagnosis from plausible code alone.

Separate observed symptoms, hypotheses, and reproduced causes. Use focused experiments where needed. Explain what each meaningful reproduction establishes and what remains uncertain, then return the smallest justified fix boundary.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).

Follow [mandatory checkpoint commits](../../../AGENTS.md#mandatory-checkpoint-commits): small local commits on `dev` are mandatory at each meaningful checkpoint, including failing code/test-loop states. Report owned changes and exact passing/failing/unrun checks immediately; the coordinator commits before the next slice in a shared checkout. Commit yourself only with assigned Git ownership in an isolated checkout. Read-only roles report checkpoints without Git mutations. Include checkpoint hashes and remaining failures in handoffs; do not defer all commits until final success.
