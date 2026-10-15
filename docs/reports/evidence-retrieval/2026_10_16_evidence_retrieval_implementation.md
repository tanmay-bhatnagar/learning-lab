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

## Domain/probe passing checkpoint

Coder implemented the pure module at 4aa18d7. Root verified 55 tests plus 21 subtests across evidence requests and the existing model gateways; Ruff check/format and the engineering checker pass. Production routing is not enabled. Independent tester review is the next gate before pushing this milestone.

The installed qwen3.5:4b-q8_0, think off, context 8192 accepted the flat schema in an ignored synthetic probe: direct answer 4.490s, missing comparison requested `Method B Appendix B` in 3.934s, unsupported mortality question abstained in 4.179s. Ordinary synthetic answer took 3.388s. These are single compatibility observations with different prompt sizes, not a latency or answer-quality benchmark. Existing keep_alive=0 remains unchanged and no model remained resident afterward. Raw evidence and the preserved first rejected output are under `.local/verification/reports/evidence-retrieval/answer_or_search_probe.json` and `answer_or_search_first_attempt.json`; the harness is beside them.

The first attempt mixed answer/search fields and was rejected; stronger branch examples produced valid outputs. The model also omitted inline E markers while explicitly declaring source_labels. Alternatives considered were requiring inline markers or accepting structured source declarations while validating any markers that do appear. We chose the latter: source_labels is the explicit identity contract, all inline markers must be declared, and the UI must resolve these labels to filenames/pages. This permits ordinary readable prose without treating undeclared or invented markers as valid. It verifies identities, never that a claim follows from a passage. Source-panel behavior and full production-prompt reliability remain for integration/usage validation.

Root traced production hashing through `lab/parse_pipeline.py` and `lab/hashing.py`: indexed text hashes are SHA256 of the stored full text, matching the new validator. Citation excerpts are not suitable hash inputs. Final runtime tests still need actual parsed/indexed documents rather than relying only on handcrafted records.
