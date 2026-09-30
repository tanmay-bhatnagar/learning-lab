# Review checklist

- Does the changed user flow meet the acceptance criteria, including failure paths?
- Are dependencies explicit, caller inputs preserved, and business decisions separated from I/O?
- Are module responsibilities clear without redundant abstractions or hidden state?
- Do validation, errors, cancellation, concurrent access, and partial persistence preserve the relevant contracts?
- Are originals and topic boundaries enforced by the implementation?
- Are durable formats and frontend/backend contracts compatible, or is migration handled?
- Does a test or real workflow exercise the actual defect rather than merely its mock?
- Are model/parser assumptions grounded in the installed version and a relevant sample?
- Does production code avoid test-only branches, with fakes implementing the production interface?
- Do domain modules raise domain errors, leaving status codes to the HTTP layer? Is every blind catch at a reporting boundary with a stated reason?
- Is configuration read only at the composition root, and is every import free of side effects?
- In the web app: are decisions pure and tested, effects in hooks, updaters pure, browser-boundary data parsed with `zod`, and async work aborted on unmount?
- For a refactor: did characterization tests land first and stay unchanged, are mechanical commits proven mechanical, and were resolved exemptions removed?
- Are comments minimal and public/non-obvious contracts documented?

Report actionable findings with severity, trigger, consequence, and exact location. Verify suspicions before reporting them as defects. Separate blockers from improvements; no quotas or invented findings. Model agreement is not proof. State coverage and unverified behavior even when no findings remain.
