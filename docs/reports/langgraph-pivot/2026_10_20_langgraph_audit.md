# Independent LangGraph audit and repairs

Date: 20 October 2026. Separate consolidated post-implementation audit record; preserves Claude's [implementation record](2026_10_20_langgraph_implementation.md), [pivot plan](pivot_to_langgraph.md) and prior dated research/design. Baseline `e86a092`, clean `dev` synchronized with origin at start. User explicitly authorized subagents and audit/test/fix, especially architectural adherence. Coordinator owns integration/Git/docs; reviewer owns independent architectural assessment, tester owns bounded lifecycle/reproduction checks, coder owns one assigned repair slice at a time. All acknowledge the full Code-root policy. Raw assignments/logs/reproductions remain ignored under `.local/verification/reports/langgraph-audit/`.

## Baseline evidence

Fresh coordinator `make test`: 848 backend tests plus 21 subtests (75.24s), 236 browser tests across 41 files. Engineering, global Ruff, Python formatting (147 files), web ESLint/Prettier and production TypeScript/build pass. `pip check` reports no broken requirements. Existing dependency warnings, Zod/Rollup annotations and bundle-size warning remain. This establishes a passing baseline, not absence of bugs or full architectural compliance. Log: `baseline-tests.log` in the ignored audit folder.

Read-only architecture review compares the implementation against all 16 plan gates and functional/module rules, rather than accepting completion notes. Behavioral review independently probes task/channel/ASGI/publication failures. Actual isolated usage is a separate proof layer using owned launcher session 64118, ports 5173/56702 and run `.local/verification/20261020-143213-847af780/`; no personal topic/CV is used.

## Confirmed first finding: unexpected opt-in exception leaks

Reviewer reproduced a P2 in `workflows/chat_stream.py`: `_optin_mark_failure` records `str(error)` as a public workflow error. Opt-in publication then exposes that message in terminal NDJSON. A synthetic OSError containing a private-style CV path and canary appeared literally in the public result. Ordinary chat sanitizes unexpected failures; the opt-in wrapper must do likewise. The helper probe proves leakage at that boundary; coder is adding a real graph-path regression before repair.

Chosen repair: fixed safe learner message with type-only diagnostic information where useful. Merely stripping one example path is insufficient; suppressing the error entirely would conceal failure. Preserve domain-error behavior and original exception handling where needed without storing/logging raw exception values. Coder owns only the stream boundary and focused tests; red regression must be committed before implementation. Reviewer independently rechecks after repair. No claim of closure until the graph/public-event regression and relevant suites pass.

## Other checks in progress

Reviewer also reports that `PublishOnce` is annotated as generic at consumers but is not actually generic; runtime annotation resolution fails. This is a separate typed-boundary repair candidate, not mixed into privacy work. Tester is investigating the pre-existing Stop-before-headers form resubmission/history issue documented by Claude, while continuing graph lifecycle checks. All new findings, red/repair commits, actual usage and limitations will be recorded below; neither known defects nor untested behavior are treated as passing acceptance.
