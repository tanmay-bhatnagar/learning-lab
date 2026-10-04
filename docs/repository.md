# Learning Lab code repository

The application and engineering tools live in this independent Git repository. `dev` is the development branch; `main` is reserved for releases. Remote: [tanmay-bhatnagar/learning-lab](https://github.com/tanmay-bhatnagar/learning-lab).

Start with the [README](../README.md), [current R1 snapshot](../references/R1/README.md), [system map](../references/R1/system-map.html), and [architecture](architecture.md). The older design notes in `../../design/` record how the scope was chosen.

Personal learning topics, uploads and conversations live in `../Learning/<topic>/` and do not belong in this public repository. `data/external/benchmark_PDFs/` contains the public parser corpus; `data/external/modelweights/`, runtime state, credentials and private material are ignored. The model currently has no shell, browser or hardware tools.

Follow [AGENTS.md](../AGENTS.md) and [engineering.md](engineering.md) for changes. Small local checkpoint commits on `dev` are mandatory, including failing code/test-loop states; see [checkpoint policy](../AGENTS.md#mandatory-checkpoint-commits). Push to `dev` only within explicit user authorization; merge to `main` for releases. The Code repository is exempt from the parent Second Brain's three-level directory limit.

## Instruction ownership

Open Code as the Codex development project. [Code-root AGENTS.md](../AGENTS.md) contains the entire mandatory development and exploration policy; all six roles and skills follow it without reading the parent file as coding instructions. The parent learning_lab/AGENTS.md is the shared learning-model runtime policy. The browser backend reads that file before every chat request and passes its full text into prompt assembly. The configured path is independent of topic storage; [runtime policy loading](runtime_policy.md) documents overrides and failure behavior. Neither a policy file nor a skill grants model tools.

Start a fresh Codex chat/session from Code after changing the project association or instruction files. Check the actual working directory and Git root rather than assuming an existing chat moved: this project's Git root must be Code. A reused chat can retain its earlier working directory and initial instruction context.
