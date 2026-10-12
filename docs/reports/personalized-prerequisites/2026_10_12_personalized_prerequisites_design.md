# Design report: CV-gated personalized prerequisites

Date: 12 October 2026. Role: design, read-only (Sol Medium). Proposal for discussion; application implementation needs subsequent authorization. This separate report faithfully records the completed design agent findings after research checkpoint `f0337e6`. Coordinator synthesis lives in the dated plan; earlier Document Map history remains unchanged.

Designer acknowledged the entire Code-root policy and read the design skill, architecture/engineering, research/plan notes and current source/summary/persistence/gateway/import code. No application/docs writes, Git mutations, installations, personal CV/topic access or model experiments occurred.

## Settled user requirements

On demand, same selected local model with fresh messages. A CV explicitly supplied for purpose is mandatory: missing/ineligible CV blocks this feature and asks for it, with no questionnaire substitute. CV is not proof of comfort/competence/mastery. High/medium requirements exclude initial library lists or implementation recipes. EVERY requirement independently asks whether already comfortable, even when mentioned in CV. Feedback drives refinement; deeper/course discussion uses the selected existing main conversation, with no side chat/autonomous course engine. Preserve full-source/runtime-policy/local-model/topic-isolation/explicit-action boundaries.

## Proposed learner flow and feedback

Explore prerequisites in the selected Map section, independently of a saved summary. Show section, CV status and preparation goal. Missing eligible CV shows Supply CV; ordinary chat and Map navigation remain available. Dedicated CV acquisition shows extraction/warnings for inspection/correction/replacement and makes no model call.

Generate prerequisites explicitly sends complete canonical section, eligible complete CV, fresh runtime policy and task, plus optional goal. Progress/Stop appear; cards become actionable only after complete structured output validates and saves.

Each card contains broad requirement/scope, why it matters here (generated inference and section refs), CV relationship (direct/related/not evidenced and server-resolved actual excerpts), its individual comfort question, and Comfortable / Needs a refresher / New to me / Not sure with optional editable clarification. Recommend all cards together rather than a forced wizard, so the learner compares the list while answering each independently.

Saving answers calls no model. Deterministic preparation treatment is lower priority for Comfortable (still visible), short review for Refresher, foundational preparation for New, clarify for Not sure, and explicit pending for unanswered. These are routing suggestions/self-reports, not mastery classifications. They do not rewrite the original model rationale or silently remove requirements.

Continue in the visibly named selected conversation imports a saved immutable snapshot, focuses that existing chat and optionally prepares an editable refinement draft. Sending is the learner's action. Default refinement happens in ordinary main chat. A later explicit Revise this list action is possible, but automatic inference per answer is excluded.

## CV scope, purpose and acquisition

**Evidence:** Ordinary Docling uploads index study files; FileRecord lacks CV purpose; empty-selection developer retrieval can search all indexed topic files. [Research report](2026_10_12_personalized_prerequisites_research.md) contains source references.

**Alternatives:** Designate existing study attachment; dedicated topic CV; reusable workstation CV with explicit topic grants.

**Recommended first branch:** Dedicated versioned topic CV through its own route, using parser capabilities while excluding CV from files.json, retrieval index, chat attachment choices and map storage. No filename inference. Defer existing-file designation: retaining/removing the study/index role needs an explicit contract, and copying a study upload into a CV resource does not make the old copy private.

**Tradeoff/user choice:** Topic-only preserves current boundaries but repeats CV supply across topics. Workstation reuse is convenient but needs explicit access/revocation/version rules. Scope remains the user's decision; no silent global grant.

Searchable PDF first is the smallest app-supported input. Pasted actual CV text is another credible user choice, not questionnaire substitution. DOCX/OCR deferred. Library formats do not establish app support: [Docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/). User settles scope/formats; code verifies exclusion from study retrieval, usage extraction preview. Broaden formats only on demand with adapter validation.

## Goal, scope and budget

**Alternatives:** No goal; optional topic goal; mandatory new goal before each assessment.

**Recommended branch:** Show/include existing optional user-authored topic goal as context. If absent, show Goal: understand this section, without another gate. Do not invent coding preparation for reading-only intent. Inferred dependencies beyond section source must be identified as uncertain gaps, not falsely sourced facts.

Use full canonical selected-section scope and CV, not a generated summary, top-k retrieval or compressed generated profile. section_summary.section_sources supplies complete scope; chat already has user-authored goal context but summaries omit it. Goal inclusion is a new task-specific recommendation.

Complete inputs repeat cost and can exceed context: refuse overflow, never silently omit. Research's synthetic 10,326-input-plus-reserve result demonstrates pressure, not actual CV quality/token count. Code tests full-input identity/refusal; usage reading versus reproduction. Reconsider compact profiles/broader scope after measured recurring failures and coverage/correction design.

## Structured output and EVERY-item question

**Alternatives:** Prompt-only JSON; optional schema on existing gateway; separate client/framework.

**Recommendation:** Optional output-schema keyword on ModelGateway.stream_chat and OllamaGateway; existing calls retain defaults. Send documented Ollama format through the same local verification, context/lock/cancellation/error path. [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs/) documents capability; installed daemon/model/thinking compatibility remains UNTESTED.

Proposed output fields: requirements[{title, level:high|medium, why_here, section_source_labels[], cv_relation:directly_mentioned|related|not_evidenced, cv_explanation, cv_source_labels[]}], limitations[]. App assigns IDs after validation and deterministically attaches each comfort question. Model cannot control question omission. Distinct CV/section labels and server-resolved excerpts bind evidence; each requirement needs section relevance references and evidenced CV relations need CV refs. Not evidenced never means unfamiliar.

Provisional quality-spike limit: no more than eight terse items. Empty results need explicit validated explanation/source references, not silent no-prerequisites success. Valid shape/refs do not prove relevance or pedagogical sufficiency; cap/reserve may need adjustment. Fake-HTTP tests preserve ordinary calls; real selected-model spike tests schema/format/thinking. Prompt-only fallback only after concrete incompatibility, with identical validation. No automatic repair call or actionable partial JSON.

## Versioned resource and API proposal

Keep personalized assessments out of strict native map schema. New resource schema v1 means old topics have no CV/assessments and need no map migration; validate relationships and reject unsupported/corrupt records visibly.

CV records: purpose/resource/version, immutable original identity, parser/extraction version, canonical source units/text/warnings, optional distinguishable correction revision, active/revoked state/timestamps. Replacing CV creates version; editing extraction creates correction revision. Sparse readable CV can qualify; omissions are not evidenced.

Assessment identity binds topic, map/document revision, section/source digest, CV purpose/version/effective correction digest, exact goal or explicit default, prompt/schema/policy/model settings, attempt identity/status, immutable validated requirements/evidence, and separately versioned user answers. IDs belong to exact assessment. New assessments ask EACH question again, never transfer by name similarity; prior responses remain historical, not global mastery memory.

Proposed routes:

- GET/POST /api/topics/{topic}/prerequisite-cv
- POST .../prerequisite-cv/{version}/corrections
- POST .../prerequisite-cv/{version}/revoke
- POST /api/topics/{topic}/files/{file_id}/map/sections/{section_id}/prerequisite-assessments
- GET /api/topics/{topic}/prerequisite-assessments/{assessment_id}
- PUT .../{assessment_id}/answers/{requirement_id}
- POST /api/topics/{topic}/conversations/{conversation_id}/prerequisite-imports

Generation receives displayed source/CV versions and model/context/thinking settings; server reconstructs evidence/instructions. Answers receive expected revision and allowed comfort/clarification, not client-authored replacement requirements. These routes assume recommended topic scope and must change if user chooses reusable CV.

## Lifecycle, stale results and revocation

Reuse topic lease, shared model lock and finalized cleanup. Full policy/evidence/CV fit preflight precedes accepted generation; no history trimming/multipass. Attempts: generating/completed/cancelled/error/interrupted. Publish only on provider completion plus validation and atomic save; failed regeneration preserves previous completed assessment as historical. Partial JSON stays non-actionable.

Capture topic/section/CV/attempt IDs. Source, CV or goal changes mark old proposals historical; new generation/handoff require current dependencies. No automatic refresh. Answer saves use topic storage and optimistic versions. Stop/source/topic/unmount cancel; abandoned requests recover interrupted, Retry explicit, model-lock waiting cancellable.

Revoke/replace cannot report success while an old request may publish. Cancel owned assessment, acquire topic lease, change eligibility, and check effective CV identity again before publication. Expose busy/Stop when another operation prevents this; never pretend immediate revocation.

**Recommended removal semantics:** Revoke future prerequisite use, preserving originals and earlier assessment/import history. Blocks new personalization/handoff from revoked CV, but earlier imported content may remain in ordinary chat history. Do not label it delete/forget. Erasure, including historical imports, is separate retention/deletion scope and must be settled if expected.

## Existing main-chat handoff

Use distinct prerequisite_import metadata, not summary_import. Snapshot includes assessment/answer revision, section/source identity, requirements/rationale/refs, answers or explicit pending, relevant CV excerpts/correction provenance, model/time and generated-inference/self-report distinctions. No whole CV by default.

Put those distinctions in actual message content because history_messages drops display metadata. Ordinary history can trim imports; no permanent injection promise. Capture/names selected existing conversation. Idempotency includes destination+assessment+answer revision. Changed answers permit a new explicit snapshot; retry same snapshot never duplicates.

Recommend allowing pending-answer handoff: EVERY question is present, but unanswered stays pending and ordinary conversation remains available. After import, optional editable draft: Refine these preparation suggestions using my responses, staying at high/medium level. Never auto-send or constrain where later conversation goes.

## Independent modules and implementation milestones

When authorized: learner_cv pure records plus CV store; prerequisites pure evidence/prompt/schema/validation; assessment store for attempts/proposals/versioned answers; prerequisite_import pure snapshots/identity; thin HTTP routes; frontend schemas, pure state, hooks, presentational cards. One writer owns shared gateway/contracts/composition. No general profile/course/workflow framework.

Sequence: discussion/decision checkpoint; isolated quality/compatibility spike (small optional gateway seam only if authorized); CV purpose resource/exclusion/preview/correction/replacement/revoke; assessment backend/full preflight/structured lifecycle; every-item feedback/reload/edit/concurrency/pure grouping; immutable captured main-chat handoff; independent review/real usage/static/tests/build and learning notes. Commit EACH meaningful code/test checkpoint on dev, including failures, with coordinator-owned Git and paired walkthrough/durable explanation.

## Quality gates and change conditions

Synthetic CV/public or synthetic source only. CV Python mention still asks comfort/no mastery; omission is not unfamiliarity; related versus direct evidence distinguishable; reading versus reproduction goals change appropriate recommendations; high/medium scope without library checklist; EACH app-created question; invalid/refusal/empty/length/partial output never actionable; actual schema/thinking/local model/output reserve works; refs/excerpts match, human-review rationale and missing dependencies; complete input/serialization/cancellation preserved. Systematic format/pedagogical failures prevent generation readiness. Code owns contracts, research/usage real evidence, coordinator scope decisions. Change scope/formats/list cap/settings/source strategy only from identified failure or explicit preference.

## User decisions and recommended defaults

Two immediate choices: topic-specific versus reusable workstation CV with explicit topic access; searchable PDF only versus PDF plus pasted actual CV text. Offer defaults for review: all comfort cards together, optional visible topic goal, main-chat refinement, pending answers allowed, revocation distinct from erasure. Mandatory CV/same model/EVERY-item checks are settled.

## Evidence and limits

Design performed read-only repository inspection and reused sufficient research; no new lookup/experiment needed. Research reported 48 focused existing tests plus 13 subtests; designer did NOT rerun them. Real CV extraction/Ollama schema/thinking/new browser/build/pedagogical quality remain unrun. No new feature is implemented. Coordinator owns report/plan documentation and checkpoint commits.
