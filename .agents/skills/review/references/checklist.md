# Review checklist

- Does the changed user flow meet the acceptance criteria, including failure paths?
- Are dependencies explicit, caller inputs preserved, and business decisions separated from I/O?
- Are module responsibilities clear without redundant abstractions or hidden state?
- Do validation, errors, cancellation, concurrent access, and partial persistence preserve the relevant contracts?
- Are originals and topic boundaries enforced by the implementation?
- Are durable formats and frontend/backend contracts compatible, or is migration handled?
- Does a test or real workflow exercise the actual defect rather than merely its mock?
- Are model/parser assumptions grounded in the installed version and a relevant sample?
- Are comments minimal and public/non-obvious contracts documented?

Report actionable findings with severity, trigger, consequence, and exact location. Verify suspicions before reporting them as defects. Separate blockers from improvements; no quotas or invented findings. Model agreement is not proof. State coverage and unverified behavior even when no findings remain.
