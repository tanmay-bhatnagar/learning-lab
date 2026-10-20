# Runtime learning policy

The browser backend reads the complete learning-agent policy before every Default or named-conversation chat request, independent of the selected model. The authoritative default is `learning_lab/AGENTS.md`, outside Code; Code-root `AGENTS.md` remains development guidance and is not included in learning prompts.

## Configuration and request behavior

`AppConfig.runtime_policy_path` defaults to `CODE_ROOT.parent / "AGENTS.md"`. Set `LEARNING_LAB_POLICY_PATH` for a different deployment layout, or pass `runtime_policy_path` explicitly to configuration/application construction. Explicit configuration takes precedence over the environment. Changing `LEARNING_LAB_ROOT` does not change policy authority. Restart the API after changing the configured path; editing the file contents applies to the next chat request without restarting.

Each request selects attachments, then reads one complete UTF-8 policy snapshot before retrieval, embedding, generation, or saving a conversation turn. The pure prompt builder includes the snapshot in the protected system message alongside existing capability restrictions, the application-validated active topic ID and logical `Learning/<id>/` binding, and the separately labeled user-authored learning goal. It uses the validated ID rather than a user-authored topic name or an absolute filesystem path. It never reads Code's instructions or other topics. Current models still have no filesystem, shell, browser, or device tools.

A missing, unreadable, blank, or invalid UTF-8 file blocks chat with a visible HTTP 500 error, finalizes the preflight error trace, and releases the topic lease. Other API operations remain available. There is no cached or short-policy fallback. Repairing the configured file allows a subsequent request to proceed. No session/citation persistence format changes are needed.

## Context budget

The policy is retained intact and consumes the same context budget as other system text. An insufficient budget returns HTTP 422 before saving the user turn or generating an answer. The current conservative estimate counts one token per UTF-8 byte. The roughly 7.4 KB policy plus capability restrictions cannot fit an 8192 context under that estimate; use 16384 or the normal 32768 limit, allowing additional room for goals, evidence, history, and generation. Never shorten policy merely to make a request fit.

## Ordinary conversational explanations

The authoritative local runtime policy includes this guidance verbatim. This committed excerpt is documentation: the app reads only its configured policy file. Deployments using a different file must apply this guidance there as well; a Code checkout alone does not update an external policy.

> In ordinary chat, finish a user-facing learning explanation with one simple question about a relevant idea. During a structured answer-or-search decision, put that question only inside the user-facing text in the returned answer action's `answer` Markdown field. Keep the required JSON structure intact: never append the question outside JSON or add it to a search action. Do not apply this rule to non-chat summaries, prerequisite JSON, or administrative acknowledgments. Do not create a separate quiz mode or grade or score the user. The user's next reply may answer the question and steer the conversation at once; respond constructively to any feedback or gaps, then follow the new direction. If the user skips the question, continue without treating it as a blocker. Never change My proficiency automatically from conversation; changes require an explicit supported user action. Follow explicit user preferences about whether to ask a question.

The question supports an ordinary exchange about the material; it does not create a separate assessment workflow or update proficiency state. The user can answer, correct the explanation, or move to another topic in the same reply.

## Design evidence and limits

A per-request read makes edits effective immediately and prevents silent use of stale instructions after deletion. A startup snapshot would be cheaper but would require a restart to refresh or invalidate policy. A path independent of topic storage avoids accidentally selecting a different authority when testing or changing data roots. The small local read keeps this increment bounded.

Ollama accepts system messages through the [chat API](https://docs.ollama.com/api/chat); interpretation depends on [model templates](https://docs.ollama.com/modelfile). Verified prompt inclusion does not prove universal model obedience. Topic/path validation and existing tool restrictions remain application responsibilities; prompt text is not a sandbox.

Tests use explicit isolated policy fixtures. Verification uses an isolated snapshot of the full authoritative file. Retrieval evaluations record an isolated policy snapshot and its fingerprint because policy changes can change retained evidence at the same context limit. Historical benchmark scores remain historical and must not be relabeled as a run of the new prompt.

## Verification — 4 October 2026

- The full backend suite passed 282 tests plus 21 subtests, including installed-model and synthetic Docling checks. All 90 frontend tests, the production web build, frontend lint/format checks, engineering validation, Ruff, Python formatting, and the CI strict tooling gate passed.
- Isolated browser verification captured four real Ollama requests across Qwen 3.5 4B and 9B: Default and named conversations, a policy edit reflected on the next request, and recovery after a missing-policy failure. The missing-policy attempt produced no model request or saved turn and retained its preflight error trace. Default history survived reload.
- A model response initially claimed no active topic despite the selected browser topic. The harness now supplies the validated ID and logical directory explicitly. A targeted real 9B/browser follow-up identified the correct topic and answered its synthetic arithmetic question; both-route regressions check topic binding and absence of other IDs or absolute paths. A final-source real 9B API check captured the exact condensed topic-context wording and complete policy, and its saved answer returned the selected ID and the expected arithmetic result.
- Independent review caught and closed standalone-CI policy dependencies, a test-fixture teardown ordering issue, and evaluation snapshot provenance drift. The original tokenizer regression passes unchanged; a mutated evaluation policy snapshot is rejected with the initial fingerprint retained.
- CI-style HTTP verification passed with an explicitly selected tracked synthetic policy fixture, confirming upload/conversion/original preservation without requiring a parent workspace. The launcher supports `--runtime-policy` for that purpose; ordinary local verification defaults to a full authoritative-policy snapshot.

Local evidence is retained under ignored `.local/verification/20261004-runtime-policy/`, with the active-topic browser follow-up under `.local/verification/20261004-runtime-policy-topic-context/` and the final prompt check under `.local/verification/20261004-runtime-policy-final-contract/`. Capturing proxies forwarded real model requests but buffered responses, so these browser captures do not certify incremental streaming cadence. The backend suite also exercises the production streaming adapter. Model responses remain observations rather than an obedience guarantee. The full three-paper evaluation and 107-PDF corpus were not rerun; older scores remain dated historical results. No personal topic was accessed, and no commit or publication occurred.

Restart an already running API once to pick up the backend changes. Subsequent edits to policy contents apply to the next chat request; changing its configured path requires restarting the API.
