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

## Errors

Domain code raises domain errors; only the HTTP layer knows status codes. `lab/errors.py` owns the taxonomy and one exception handler in the HTTP layer maps it, keeping today's status codes and messages:

| Error | Meaning | Status |
| --- | --- | --- |
| `InvalidInput` | The request or a value inside it is malformed | 400 |
| `Forbidden` | A path-safety rule refused access | 403 |
| `NotFound` | A topic, file, attachment or asset does not exist | 404 |
| `Conflict` | The resource is not in a state that allows the operation (busy topic, conversion incomplete, not indexed, index missing) | 409 |
| `TooLarge` | The payload exceeds a configured limit | 413 |
| `DoesNotFit` | The selected material cannot fit the context limit | 422 |
| `CorruptData` | Saved data cannot be read; the user must restore it | 500 |

Degradation signals such as `EmbeddingUnavailable` are caught by the caller that owns the fallback, which reports the degradation as a warning. Parser and converter `ValueError`s become the file record's `error`. Programming errors (`TypeError`, `KeyError`, `AttributeError`) are never caught to produce a user-facing message.

A blind catch (`except Exception`, TypeScript `catch` without a binding) is allowed only at a boundary that reports the failure, and it states why on the same line (`# noqa: BLE001 - reason`, or a comment opening the `catch` block). Ruff and `check_engineering.py` enforce this.

## Configuration

Configuration is read once, at the composition root, into a frozen `AppConfig` (`lab/config.py`) and passed down. Only that module reads the process environment; `check_engineering.py` enforces this for `lab/`. Importing a module has no side effects: no app construction, no environment reads, no directory creation. Scripts are entry points and may read their own environment. Defaults that point at personal data (the `Learning/` root) are never used by tests or verification, which always pass isolated roots.

## Test seams

Production code has no test-only branches. An injected dependency follows exactly the production path, with the same call signature, locks and dispatch; a test fake implements the production interface (`ModelGateway`, `Store`, the parser map) rather than a simplified one. If a behavior cannot be tested without a special branch, change the design so the decision is a pure function, then test that function directly.

## Frontend

The functional rules above apply to TypeScript and React as well.

- Components render. Decisions (stream-event folding, file selectability, context meters, activity guards) are pure functions in `src/state/` or `src/domain/` with their own tests.
- Effects live in hooks (`src/hooks/`). Components do not call `fetch`, `localStorage` or `window` directly. Refs hold DOM nodes and `AbortController`s, not application state.
- One operation runs at a time per activity; represent it as a union (`idle | sending | uploading | …`) and derive guards from it, not from parallel booleans.
- `setState` updaters and reducers are pure. React may call them twice.
- Every value crossing the browser boundary (HTTP responses, stream events, `localStorage`) is parsed with a `zod` schema in `src/api/`; the schema is the source of the TypeScript type. Status fields are unions shared with the domain rules.
- URLs are built in one module (`src/api/urls.ts`).
- Asynchronous work started by a component or hook is aborted when it unmounts or its input changes.
- Formatting is Prettier's; ESLint enforces `react-hooks` and `no-empty`. There are no line, file, function or complexity limits; split a file when its responsibilities diverge, not to satisfy a number.

## Behavior-preserving refactors

1. Write down the observable behavior to preserve: the API contract (`docs/API.md`), stored formats, and user flows. Stored-format changes need a separate compatibility decision.
2. Land characterization tests first, in their own commit, passing against the current code. They test behavior through public interfaces, not the internals being moved.
3. Keep mechanical changes (formatting, moves, renames) in their own commits and prove them mechanical: equal Python ASTs, equal TypeScript syntax trees, or byte-identical outputs on a fixture. `git diff -w` is not enough when quotes or wrapping change.
4. Make structural changes in small slices, each with its checks passing. Do not change characterization tests to make a slice pass; a needed change is a behavior change and is reported.
5. One writer per path. Parallel slices use isolated worktrees; the coordinator merges and reruns every check.
6. Each slice removes the lint and structure exemptions it resolves (`ruff.toml` per-file ignores, `PENDING` in `check_engineering.py`, the ESLint override list) so the ratchet only tightens.

## Comments, types, and docs

Inline comments are rare: retain only a non-obvious reason or constraint that names/types cannot express. Do not add narration, commented-out code, or decorative section markers. Trust agents to read code.

Public functions and non-obvious helpers get useful docstrings covering contracts, assumptions, effects, and meaningful failure conditions. Do not restate the signature. Type public boundaries. Avoid `Any`, unsafe casts, and TypeScript suppression unless the external boundary genuinely requires them and the value is validated.

## Work ownership

Define acceptance criteria before implementation. Use the smallest useful design and handoff; no mandatory six-agent ceremony. The coordinator integrates changes. Assign disjoint write paths or separate checkouts and settle shared interfaces first. Reviewers report issues; they do not silently implement changes. Model escalation and scope changes are explicit.

## Checks

Install engineering tools with `.venv/bin/python -m pip install -r requirements-engineering.txt` in the project environment.

- `.venv/bin/python scripts/check_engineering.py`: role/skill wiring, local documentation links, supported config shape, and structure: no `fastapi`/`starlette` import in `lab/` outside the HTTP layer, no environment read outside `lab/config.py`, no TypeScript `catch` that discards an error without a reason.
- `.venv/bin/python -m ruff check .`: Python errors, bug patterns (`B`), shadowed builtins, blind excepts and, in `lab/`, parameter and return annotations. Unused exemptions fail (`RUF100`).
- `.venv/bin/python -m ruff check --select E4,E7,E9,F,I scripts/check_engineering.py scripts/verify_workspace.py tests/test_verify_workspace.py`: stricter checks for the setup tooling.
- `.venv/bin/python -m ruff format --check .`: Python formatting.
- `npm run --prefix apps/web format:check` and `npm run --prefix apps/web lint`: Prettier and ESLint for the web app.
- `make test`: Python tests (pytest) and web tests (Vitest with Testing Library and jsdom).
- `make build`: TypeScript strict checking (including `noImplicitReturns`) and the production web build.
- `.venv/bin/python scripts/verify_workspace.py`: real HTTP upload/conversion/persistence checks in an isolated workspace.

Existing offenders are listed explicitly: per-file ignores in `ruff.toml`, `PENDING` in `check_engineering.py`, and the override list in `apps/web/eslint.config.js`. New code may not add entries without a stated reason.

CI uses macOS and the existing Python 3.13 dependency lock, matching the current supported development setup. It runs these checks without Ollama or model downloads. Browser verification and real-model/parser evaluation remain explicit checks; CI passing does not certify them. Functional purity and module cohesion still require review; the checks catch only the patterns listed above.

## Provenance

Procedures adapt selected ideas from [pstack](https://github.com/cursor/plugins/tree/69cf06fa253ba0761213669171198968e51fb9ff/pstack): how/why, architect, bug-fix/TDD, interrogate, verification, and encode-lessons-in-structure. These are project-specific rewrites, not an installation of pstack or its autonomous shipping workflows. Attribution and upstream license: `third-party/pstack-LICENSE.txt`.

Codex discovery/configuration follows the official [skills](https://learn.chatgpt.com/docs/build-skills) and [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) documentation. Open this repository as the project to discover its local skills and agents. A session opened in a parent repository does not automatically discover skills in this child repository. Start a fresh project session after setup; confirm role/model availability there.
