---
name: review
description: Independently inspect proposed changes for defects and maintainability risks.
---

# Review

Use this procedure for Learning Lab development. Read the root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/review.toml`; invoking this skill alone does not switch models.

Read the requirement and actual diff plus affected callers. Apply references/checklist.md. Challenge assumptions independently of the implementer's summary; reproduce suspected problems with read-only or isolated checks when permitted. Do not edit source, install dependencies, or run commands that mutate the live workspace. Return prioritized actionable findings with trigger, consequence, location, and evidence. Distinguish confirmed defects from unverified concerns. If there are no findings, say so and list the meaningful coverage gaps. Send findings to the coordinator; do not delegate or apply fixes yourself.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).
