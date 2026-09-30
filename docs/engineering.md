# Engineering conventions

## Functional programming

- Business decisions are pure functions: identical inputs produce identical outputs and no external changes. Pass settings, timestamps, identifiers, and dependencies explicitly.
- No mutable global application state. Constants are fine. Framework-managed app-lifetime resources must have explicit ownership, isolation, and lifecycle; do not hide the active topic or conversation in a singleton.
- Do not mutate caller-owned lists, mappings, records, or nested values. Return updated values. Local mutation of a newly owned buffer is acceptable when it improves clarity or performance and never escapes as shared mutable state.
- Keep filesystem, database, network, clock, randomness, and model calls in boundary functions. Passing an I/O capability makes it explicit, not pure.
- Separate decisions from effects: decide whether an index needs rebuilding with pure inputs, then let orchestration run the rebuild.
- Prefer composition, typed plain data, and small interfaces over inheritance or stateful service objects. Use frozen records/readonly types where useful; do not add wrappers just to label something functional.
- Framework classes (Pydantic, ASGI middleware, library adapters) are allowed. Keep business decisions in functions. Existing classes are not a mandate for an unrelated rewrite.
- Each module owns a cohesive responsibility and hides its implementation details. Avoid circular imports and modules that exist only to forward a call.
- Use explicit result types or narrow exceptions at boundaries. Do not convert failures into empty success values or catch every exception and continue silently.
- Represent state transitions deliberately. A ready status means the required durable artifacts exist. Document recovery and compatibility for partial writes and stored-schema changes.

## Comments, types, and docs

Inline comments are rare: retain only a non-obvious reason or constraint that names/types cannot express. Do not add narration, commented-out code, or decorative section markers. Trust agents to read code.

Public functions and non-obvious helpers get useful docstrings covering contracts, assumptions, effects, and meaningful failure conditions. Do not restate the signature. Type public boundaries. Avoid `Any`, unsafe casts, and TypeScript suppression unless the external boundary genuinely requires them and the value is validated.

## Work ownership

Define acceptance criteria before implementation. Use the smallest useful design and handoff; no mandatory six-agent ceremony. The coordinator integrates changes. Assign disjoint write paths or separate checkouts and settle shared interfaces first. Reviewers report issues; they do not silently implement changes. Model escalation and scope changes are explicit.

## Checks

Install engineering tools with `.venv/bin/python -m pip install -r requirements-engineering.txt` in the project environment.

- `.venv/bin/python scripts/check_engineering.py`: role/skill wiring, local documentation links, supported config shape.
- `.venv/bin/python -m ruff check .`: high-confidence Python errors. The initial config intentionally does not impose a wholesale formatting migration on existing code.
- `.venv/bin/python -m ruff check --select E4,E7,E9,F,I scripts/check_engineering.py scripts/verify_workspace.py tests/test_verify_workspace.py`: stricter checks for new setup tooling.
- `.venv/bin/python -m ruff format --check scripts/check_engineering.py scripts/verify_workspace.py tests/test_verify_workspace.py`: formatting for that tooling.
- `make test`: Python and frontend behavior tests.
- `make build`: TypeScript strict checking and production web build.
- `.venv/bin/python scripts/verify_workspace.py`: real HTTP upload/conversion/persistence checks in an isolated workspace.

CI uses macOS and the existing Python 3.13 dependency lock, matching the current supported development setup. It runs these checks without Ollama or model downloads. Browser verification and real-model/parser evaluation remain explicit checks; CI passing does not certify them. Functional purity and module cohesion require review; the linter does not prove them. Broader Python typing and frontend lint/format adoption should be introduced as scoped follow-ups rather than silently rewriting the current app.

## Provenance

Procedures adapt selected ideas from [pstack](https://github.com/cursor/plugins/tree/69cf06fa253ba0761213669171198968e51fb9ff/pstack): how/why, architect, bug-fix/TDD, interrogate, verification, and encode-lessons-in-structure. These are project-specific rewrites, not an installation of pstack or its autonomous shipping workflows. Attribution and upstream license: `third-party/pstack-LICENSE.txt`.

Codex discovery/configuration follows the official [skills](https://learn.chatgpt.com/docs/build-skills) and [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) documentation. Open this repository as the project to discover its local skills and agents. A session opened in a parent repository does not automatically discover skills in this child repository. Start a fresh project session after setup; confirm role/model availability there.
