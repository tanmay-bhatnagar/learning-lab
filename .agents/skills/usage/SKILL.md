---
name: usage
description: Operate the real application in isolation and verify user-visible outcomes.
---

# Usage

Before work, read `AGENTS.md` at the Code repository root and follow its entire [Product development and exploration policy](../../../AGENTS.md#product-development-and-exploration). This is mandatory for this role and every task. Acknowledge the policy to the coordinator. Investigate material uncertainty within the assigned scope, compare consequential alternatives, and report what was learned, the chosen approach and its tradeoffs, supporting evidence, and unresolved uncertainty. Keep exploration proportional. If existing evidence is sufficient, briefly explain why new research was unnecessary. If needed investigation exceeds the role's permissions or assignment, report that need to the coordinator before making the dependent decision.

Use this procedure for Learning Lab development. Read Code-root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/usage.toml`; invoking this skill alone does not switch models.

Read references/flows.md for launch, health checks, user flows, evidence, and cleanup. Run .venv/bin/python scripts/verify_workspace.py from the repository root using the project environment for automated HTTP proof; use --serve for browser verification. Inspect the helper before use when its behavior is unfamiliar. Drive only the task-relevant flows with synthetic input. Capture actual actions, outcomes, and persisted effects; identify mocks and unexercised model behavior. Stop only processes created by the verification run and retain evidence. Do not edit application code, use personal topics, or download models automatically. Report failures to the coordinator for debug/code follow-up.

Distinguish actual product behavior, simulated behavior, and untested capabilities. Explain meaningful learner-workflow gaps, failure behavior, and what the run taught us about the product. Investigate surprising outcomes within scope or return them to the coordinator.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).

Follow [mandatory checkpoint commits](../../../AGENTS.md#mandatory-checkpoint-commits): small local commits on `dev` are mandatory at each meaningful checkpoint, including failing code/test-loop states. Report owned changes and exact passing/failing/unrun checks immediately; the coordinator commits before the next slice in a shared checkout. Commit yourself only with assigned Git ownership in an isolated checkout. Read-only roles report checkpoints without Git mutations. Include checkpoint hashes and remaining failures in handoffs; do not defer all commits until final success.
