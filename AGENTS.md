# Learning Lab engineering

These rules apply to development in this repository. They do not grant the application agent access outside its active learning topic. Current explicit user instructions take precedence over these defaults.

## Start and route

- Read `docs/architecture.md` and `docs/engineering.md` for a substantive change. Inspect Git status before editing; preserve other work.
- The main agent coordinates scope, acceptance criteria, assignments, integration, and final verification. Use only the roles needed for the task; small changes can stay inline.
- Investigation: research. New behavior: design, code, review, usage as needed. Reported failure: debug, code, then targeted review/usage. Review findings go to the coordinator, who assigns fixes to code within the authorized scope.
- Role configs live in `.codex/agents/`; procedures live in `.agents/skills/`. Spawn the named role and have it read its skill. Reading a skill in the main session does not change the model.
- Research and review use Sol High; design uses Sol Medium; code and usage use Luna Medium. Debug starts on Sol High. Config files contain the exact IDs. Report unavailable roles/models rather than silently substituting.
- Research, design, and review do not edit application code. Debug may create a scoped reproduction or regression test; code implements fixes. Usage runs the product in isolation and reports outcomes.

## Implement

- Use functional programming: pure transformations, explicit dependencies, immutable caller inputs, and I/O at boundaries. See `docs/engineering.md` for the enforceable conventions and framework exceptions.
- Keep inline comments to a bare minimum. Use meaningful names, types, and useful contract docstrings. Do not add prose that repeats code.
- Keep changes cohesive. Do not mix unrelated refactors, generated artifacts, model weights, or personal material into a change.
- Preserve originals; retain topic isolation; expose failures and degraded fallbacks. Stored-format changes need a version/compatibility decision.
- Do not introduce compaction, autonomous execution, web research inside the app, or hardware control merely because a coding agent has those capabilities.

## Delegate and verify

- Delegation is appropriate for independent bounded tasks. Give each worker a goal, acceptance criteria, owned paths, shared contracts, and required evidence; use `docs/task-template.md` when a written handoff helps.
- One writer per path. Agree on interfaces before parallel edits. Use isolated checkouts when overlapping work cannot be avoided. The coordinator owns integration and inspects every worker result.
- Run `.venv/bin/python scripts/check_engineering.py`, relevant tests, and the web build for affected UI/contracts. A passing build is not runtime proof. Use the usage skill for changed user flows.
- Use synthetic fixtures and isolated roots for tests. Never drive a personal topic as test data. Keep local evidence under ignored `.local/verification/`.
- Review checks behavior and architecture; it does not prove absence of bugs. Preserve failure evidence and state what was not exercised.

## Deliver and iterate

- Use `dev` for development and `main` for releases. Push, merge, and release only within explicit user authorization; do not force-push by default.
- Check the staged diff for private information and unrelated work before committing. The public benchmark PDFs may be tracked; model weights and personal topics may not.
- Explain outcome, evidence, and limitations briefly. Update affected contracts/docs with behavior changes.
- Revise skills after observed failures. Prefer a regression test, stronger type, or runtime check over repeating an instruction. Do not auto-promote every one-off correction into a permanent rule.
