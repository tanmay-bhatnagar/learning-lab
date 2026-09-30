---
name: usage
description: Operate the real application in isolation and verify user-visible outcomes.
---

# Usage

Use this procedure for Learning Lab development. Read the root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/usage.toml`; invoking this skill alone does not switch models.

Read references/flows.md for launch, health checks, user flows, evidence, and cleanup. Run .venv/bin/python scripts/verify_workspace.py from the repository root using the project environment for automated HTTP proof; use --serve for browser verification. Inspect the helper before use when its behavior is unfamiliar. Drive only the task-relevant flows with synthetic input. Capture actual actions, outcomes, and persisted effects; identify mocks and unexercised model behavior. Stop only processes created by the verification run and retain evidence. Do not edit application code, use personal topics, or download models automatically. Report failures to the coordinator for debug/code follow-up.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).
