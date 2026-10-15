# Answer-or-search — implementation checkpoints

Date:16October2026. User explicitly authorizes full implementation, small meaningful code/test/fix checkpoints, a remote dev push after each passing milestone before the next slice, required agents and final end-to-end verification. This is a separate consolidated implementation/learning record; [research](2026_10_15_evidence_retrieval_research.md), [design](2026_10_15_evidence_retrieval_design.md) and [discussion/user choices](2026_10_15_evidence_retrieval_discussion.md) remain preserved.

## Accepted behavior and constraints

Use the complete answer-or-search response, not a separate sufficiency-only call. Initial search remains. Extra search is an explicit per-turn option initially off, with at most one additional selected-indexed-document lookup and at most two chat-model generations using the same selected installed model. Insufficient support yields a supported partial answer or an explanation of missing evidence. Show stage status and final supplied sources. Ordinary chat, saved conversations, proficiency, opt-in whole-CV text, protected policy/question and Stop remain supported. No new model/framework/install, native-tool requirement, side chat, autonomous workflow or compaction.

The model's sufficiency judgment remains fallible. First structured answer must be buffered and validated through provider completion before presentation/save; a search request grants no source authority. Server captures selected-file scope, never interprets an empty filter as all topic files. New evidence must survive context allocation to count as used. CV-off must not read CV artifacts; CV-on source eligibility is rechecked before subsequent model requests. Material effective-context/source/policy changes visibly stop rather than remix a turn.

## Ordered meaningful milestones

1. Strict pure protocol/source helpers and a bounded synthetic real selected-model feasibility check. No production routing yet.
2. Prompt/context integration: complete protected question/policy/learner/CV, source manifest, allocation and effective-context identity contracts.
3. Shared Default/named backend lifecycle: opt-in request, validated buffered answer or one scoped search/final inference, cancellation/freshness/persistence safety.
4. Versioned trace/answer metadata and typed browser wire compatibility (may be split narrowly if lifecycle requires fields earlier).
5. Per-turn opt-in, stage/Stop/source UI and conversation isolation.
6. Independent review/repairs, full isolated real-model/parser/browser verification, module study notes and final delivery push.

Each slice can contain separate mandatory red, repair and documentation commits. Root owns shared Git/docs, inspects staged owned paths, runs required gates and pushes the passing slice before releasing the next one. No squashing to hide red history. Workers read the entire root policy and report learning/evidence/alternatives/uncertainty. No designer rerun is needed; existing plan plus user protocol choice is sufficient.

## First assignment and decisions

Coder owns only new evidence_request domain/tests plus ignored synthetic probe. Root owns integration/contracts and all Git. Compare practical strict schema shapes with the installed gateway; the old small-decision4KiB cap is not an adequate complete-answer limit. Explicit model source references can be validated against a supplied retained-source manifest; this validates identity, not semantic claim truth. Stable short manifest labels may reduce repetitive ID output, but cannot create authority. Actual schema support, decision quality, response reserve and cold-call cost remain unmeasured until the probe. Existing app/source inspection is sufficient for this assignment; no new library research or installation is justified.

Raw assignments and experiments stay under ignored `.local/verification/reports/evidence-retrieval/`. No personal topic or CV may be used. Prior feature baseline527backend+21subtests/211web is historical, not a fresh result for this implementation. Current work starts from clean dev at32da582.

## Pure protocol red checkpoint and scope correction

Coder redf39a261 specifies complete answer/search actions, manifest source references, malformed/mixed/oversized output and scoped deduplication. Test collection fails before module creation as intended; production code is unchanged at that checkpoint. Proposed flat strict object requires action, answer, source_labels and query, with irrelevant branch fields empty. This avoids relying on unverified root-union grammar support; the real installed-model probe must establish feasibility. Manifest references validate identity, not truth of each claim.

Root integration inspection corrects a proposed test assumption: an empty retained-evidence manifest is not an empty selected-document scope. A request with selected indexed files can legitimately need another search after initial evidence is absent or trimmed. The parser's trusted can_search flag must derive from server-captured indexed selection; actual source merging rejects empty scope. Empty manifest permits no source references but can permit search. Avoid an empty enum in the provider schema; use an empty-array bound. This is a contract correction with explicit evidence/conditions, not weakening source isolation to obtain green tests. Current first slice remains gated on actual model completion, strict validation and root push before the next slice.
