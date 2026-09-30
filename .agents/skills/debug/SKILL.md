---
name: debug
description: Reproduce a reported failure and identify its root cause.
---

# Debug

Use this procedure for Learning Lab development. Read the root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/debug.toml`; invoking this skill alone does not switch models.

Start from a reported symptom and expected behavior. Reproduce on isolated inputs, trace the execution path, and distinguish the failing condition from its upstream cause. Create the narrowest useful regression test or reproduction script when practical; prove it fails for the intended reason. You may write only task-scoped reproduction/test artifacts, not production fixes. Return reproduction commands, evidence, root cause with locations, proposed fix boundary, and a failing check for the code agent. If reproduction is unavailable, state what remains hypothetical; do not claim a diagnosis from plausible code alone.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).
