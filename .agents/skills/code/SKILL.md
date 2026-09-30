---
name: code
description: Implement scoped features and fixes against agreed contracts.
---

# Code

Use this procedure for Learning Lab development. Read the root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/code.toml`; invoking this skill alone does not switch models.

Read acceptance criteria, owned paths, and relevant contracts before editing. Follow ../../../docs/engineering.md: pure business functions, explicit dependencies, preserved caller inputs, rare comments, useful docstrings. Implement the smallest cohesive change; update consumers together when a contract changes. Run a focused regression check and affected tests/build. Do not weaken tests to fit an incorrect implementation. If the contract proves wrong, report the concrete mismatch to the coordinator instead of inventing a parallel architecture. Return changed paths, verification evidence, and limitations; commit/push only when assigned and authorized.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).
