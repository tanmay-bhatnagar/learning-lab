---
name: design
description: Plan behavior, data contracts, and component ownership before implementation.
---

# Design

Use this procedure for Learning Lab development. Read the root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/design.toml`; invoking this skill alone does not switch models.

Trace the current caller and data flow. Define observable acceptance criteria, input/output shapes, owners, error states, persistence compatibility, and verification. Compare alternatives when the choice has meaningful consequences; do not require multiple prototypes for routine work. Prefer composition and cohesive modules with a small public interface. Keep I/O boundaries explicit. Return a concise design, implementation slices with disjoint ownership where possible, and unresolved decisions. Do not modify application code or create speculative scaffolding.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).
