# Answer-or-search implementation continuation

Date: 19 October 2026. Separate dated continuation of the [18 October record](2026_10_18_evidence_retrieval_implementation.md); research/design/discussion and earlier checkpoints remain preserved. This consolidates coordinator, coder and reviewer findings. Raw evidence stays ignored under `.local/verification/reports/evidence-retrieval/`.

## Resumed state

Origin/dev1254b85 contains the passing finite workflow milestone:653backend tests plus21subtests and independent31workflow plus16review cases passed. Local routing checkpoints a5bb16e/2de7e4e/7ba682b add strict opt-in, indexed-scope rejection before save, canonical captured prompt inputs and shared chat lifecycle adaptation. Initial four API tests passed, but expanded search/named/fallback/cancellation/persistence cases were not yet complete. Root resumed with tracked dirty chat.py/test_evidence_chat.py changes from the prior coder and preserved them. New coder/reviewer turns must inspect and checkpoint that work before repairs. No UI integration or full application proof is claimed.

## Acceptance and unresolved checks

The existing shared route remains the integration choice: it owns one user/assistant turn, topic lease, save-before-done, cancellation and trace finalization. The finite module owns bounded decision/search effects. Current dirty repairs align initial retrieval with captured scope, use milliseconds consistently, settle cleanup errors before persisting incomplete metadata, and apply final workflow metadata explicitly. These need verification before acceptance.

Reviewer previously identified two further cases to reproduce: buffered first-call disconnect on ASGI2.4, whose installed response implementation relies on a failed send; and initial prepared source identities being reported as supplied before any gateway invocation. These are open questions, not confirmed new defects. Application invocation attempts remain distinct from provider receipt, semantic source use or answer correctness. Root owns decisions/integration; coder owns route/schema/API tests; reviewer stays read-only. After B passes and is pushed, typed browser wire and opt-in/progress/source UI remain separate milestones, followed by isolated real parser/model/browser tests and final gates/push.
