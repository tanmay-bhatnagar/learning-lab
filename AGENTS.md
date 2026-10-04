# Learning Lab engineering

These instructions govern agents developing Learning Lab and are self-contained within the Code repository. They do not require the parent `learning_lab/AGENTS.md` for development guidance. That parent file is the application's learning-agent runtime policy; it does not grant coding permissions. Current explicit user instructions take precedence over these defaults.

The Code repository is exempt from the Second Brain's three-directory-level limit. Preserve dated design history. Do not create or operate on personal learning topics as part of development verification; use isolated workspaces. The browser backend explicitly reads the configured learning-agent runtime policy before every chat request and supplies its full text to the selected model; it does not rely on model discovery. The default is the parent `learning_lab/AGENTS.md`. Missing, invalid, or unfit policy blocks chat visibly; policy text does not grant tools or bypass application boundaries.

## Product development and exploration

Learning Lab is both a working product and an exploratory learning exercise for Tanmay.

This entire policy is mandatory for EVERY development agent, regardless of role, model, task type, or whether it is the coordinator, a named sub-agent, or an ad hoc delegate. It applies to research, design, code, debug, review, usage, documentation, maintenance, and future development roles. A narrow assignment or role procedure does not exempt an agent. Explicit user instructions and access boundaries still take precedence.

- Research is part of implementation whenever unfamiliar behavior, uncertainty, or competing approaches could materially affect the result. Use repository evidence, small experiments, and external sources as appropriate.
- For consequential choices, compare credible alternatives and explain their tradeoffs before committing to an approach. Prefer primary sources and current official documentation for technical claims.
- Share what was learned, why an approach was chosen, and what remains uncertain. Distinguish verified findings from assumptions and recommendations.
- Keep exploration proportional to the decision. Investigate enough to make an informed choice; avoid expanding a bounded feature into an unrelated research project.
- Prefer small, reversible implementations that allow useful ideas to be tested. Product reliability, maintainability, and learning value all matter.
- Development-related external research is authorized within the agreed implementation scope. Learning-session access boundaries remain in force.

Every development agent must recognize research needs within its assignment; research is not solely the research role's responsibility. Verify technical claims that depend on current versions or external behavior. Include relevant evidence and source links in results; do not invent reasons for earlier choices. Routine work supported by sufficient existing evidence does not require a fresh web search or multiple prototypes. Experiments and external research remain subject to assigned scope and permissions; this policy does not authorize installations, publication, hardware control, or web access by the application's learning model.

The coordinator must include this entire policy in delegated assignments, require workers to read Code-root `AGENTS.md`, and check adherence when integrating results. Workers must acknowledge the policy and report relevant research, what was learned, decision evidence, tradeoffs, and unresolved uncertainty. When no new research was needed, briefly explain why existing evidence was sufficient. If needed investigation exceeds the worker's role or authorization, report it to the coordinator before making the dependent decision. Carry unresolved research needs into handoffs; do not present an unverified consequential assumption as a settled decision.

### Mandatory learning delivery and decision records

- At EVERY consequential checkpoint, explain to Tanmay what was learned, the credible alternatives actually considered, the chosen approach and why its evidence/constraints favor it, meaningful tradeoffs, and what remains assumed or unverified. Explain the decision path and conditions that would change it; a diagram is optional. This is mandatory for all roles, including implementation, debugging, review and usage, not just research/design.
- Deliver that explanation in BOTH the user-facing walkthrough and durable dated design/decision notes under `docs/`. Agent reports and commit messages alone do not satisfy learning delivery. The coordinator must synthesize worker findings, preserve attribution and differing conclusions, link the notes, and check delivery before moving to the dependent slice. Read-only workers report these fields to the coordinator without writing or committing.
- Record the question/trigger, relevant evidence with repository/source links, considered alternatives and tradeoffs, selected branch with rationale, verified findings versus assumptions, unresolved questions with the next validation step/owner, and checkpoint commit references when available. Keep explanations proportional and focus on consequential choices; do not invent alternatives, reconstruct undocumented motivations, or transcribe exhaustive internal reasoning. Routine choices can cite an existing decision and explain why it still applies.
- When later evidence or Tanmay's feedback changes a choice, mark the earlier branch superseded and record the new reason; preserve dated history. State whether reports are separate or consolidated and where they are saved. Keep private/raw verification artifacts ignored; committed decision notes contain only safe, relevant evidence summaries. See [decision-record conventions](docs/engineering.md#learning-delivery-and-decision-records).

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
- Refactors follow the behavior-preserving procedure in `docs/engineering.md`: characterization tests first, mechanical commits separate and proven, exemptions removed as they are resolved.
- No test-only branches in production code; domain modules raise domain errors; only `lab/config.py` reads the environment.
- Preserve originals; retain topic isolation; expose failures and degraded fallbacks. Stored-format changes need a version/compatibility decision. Changes to application policy loading or learning-agent behavior must preserve and test runtime learning boundaries; prompt instructions alone are not tool or filesystem enforcement.
- Do not introduce compaction, autonomous execution, web research inside the app, or hardware control merely because a coding agent has those capabilities.

## Delegate and verify

- Within a plan Tanmay has approved, the coordinator may start any role without asking again. Outside an approved plan, delegate only when he asks. Give each worker a goal, acceptance criteria, owned paths, shared contracts, and required evidence; use `docs/task-template.md` when a written handoff helps.
- One writer per path. Agree on interfaces before parallel edits. Use isolated checkouts when overlapping work cannot be avoided. The coordinator owns integration and inspects every worker result.
- Run `.venv/bin/python scripts/check_engineering.py`, relevant tests, and the web build for affected UI/contracts. A passing build is not runtime proof. Use the usage skill for changed user flows.
- Use synthetic fixtures and isolated roots for tests. Never drive a personal topic as test data. Keep local evidence under ignored `.local/verification/`.
- Review checks behavior and architecture; it does not prove absence of bugs. Preserve failure evidence and state what was not exercised.

## Deliver and iterate

### Mandatory checkpoint commits

- Make small, cohesive local commits at EVERY meaningful checkpoint on `dev`: a scoped reproduction or failing regression test, an implementation slice, a code/test-loop result with tracked changes, a repair, and a durable design/documentation update. Commit before moving to the next slice, handing work off, or ending a turn with in-scope changes. Do not accumulate an entire feature into one final commit.
- Failing tests during the code/test loop MUST NOT delay a checkpoint commit. Record the exact checks run, known failures, and checks not run in the commit body; label incomplete work `wip:` or failing-test reproductions `test:`. A checkpoint preserves progress, not proof of readiness. Passing required checks remains mandatory before declaring work complete, merging, or releasing.
- Stage only owned, in-scope changes and inspect the staged diff for private information, generated artifacts, and unrelated work. Never use blanket staging in a shared dirty checkout. Preserve earlier checkpoints; do not amend or squash them merely to hide a failing intermediate state.
- The coordinator owns Git mutations in a shared checkout; workers report each checkpoint immediately with owned paths and verification status, and the coordinator commits it before assigning the next slice. A worker may commit in an isolated checkout when Git ownership is explicitly assigned. Read-only roles report checkpoints to the coordinator without writing or committing. The coordinator integrates isolated commits into `dev` in small slices and records checkpoint hashes in handoffs.
- Commit frequency and push frequency are separate. Remote pushes require explicit authorization; when authorized, push completed small checkpoints at agreed milestones rather than waiting for a huge final batch. Do not push on every test iteration unless that cadence is explicitly authorized.

- Use `dev` for development and `main` for releases. Local checkpoint commits on `dev` are mandatory and pre-authorized for in-scope development; do not wait for separate commit approval. Push, merge, and release only within explicit user authorization; do not force-push by default.
- Check the staged diff for private information and unrelated work before committing. The public benchmark PDFs may be tracked; model weights and personal topics may not.
- Explain outcome, evidence, and limitations briefly. Update affected contracts/docs with behavior changes.
- Revise skills after observed failures. Prefer a regression test, stronger type, or runtime check over repeating an instruction. Do not auto-promote every one-off correction into a permanent rule.
