---
name: research
description: Investigate code behavior and technical options with primary-source evidence.
---

# Research

Use this procedure for Learning Lab development. Read the root AGENTS.md and the relevant parts of [architecture](../../../docs/architecture.md) and [engineering conventions](../../../docs/engineering.md). Model choice is configured in `.codex/agents/research.toml`; invoking this skill alone does not switch models.

Trace the relevant code before external research. Distinguish how it behaves from why it was built that way; infer motivation only when evidence supports it. Check installed versions and primary documentation for uncertain API claims. Compare options against the requested constraints, not feature counts. Return cited facts, uncertainties, recommendation, and any small experiment needed to resolve a decision. Do not edit application code or install dependencies for an investigation without task authorization.

Use the [task handoff](../../../docs/task-template.md) when transferring substantial work. Keep findings concise and separate observed results from recommendations. Adapted from selected pstack procedures; see [provenance](../../../docs/engineering.md#provenance).
