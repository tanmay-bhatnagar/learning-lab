# Research report: CV-gated section prerequisites

Date: 12 October 2026. Role: research, read-only (Sol High). Application baseline: `6fd4d1f`. Research complete; new-feature design/implementation unstarted at report completion. This separate report is the coordinator's faithful record of the completed agent findings. Recommendations below are not implementation authorization or user-approved contracts.

The researcher acknowledged the entire Code-root policy and read its research skill, architecture and engineering conventions. No application/documentation edits, Git mutations, installations, model calls, personal CV/topic access or publication occurred. The coordinator owns saving and explaining the report before design.

## Settled requirements

On demand; same selected local Ollama model with fresh messages; a CV explicitly supplied for this purpose is mandatory (no questionnaire substitute). CV statements are evidence, not proof of familiarity. Requirements stay high/medium level, not a library syllabus. EVERY requirement asks whether already comfortable, including requirements mentioned in the CV. Feedback drives refinement; further depth/course design stays in the selected existing main conversation, without a side chat or autonomous course engine.

## CV purpose, storage and eligibility

**Verified:** FileRecord has no role, CV-purpose declaration or learner profile (`services/api/lab/contracts.py:22–43`). Store.file resolves within the explicit topic (`storage.py:149–162`). The PDF upload API automatically indexes successful Docling uploads (`web/files.py:53–109`). Ordinary chat retrieves selected attachments (`web/chat.py:166–198`), but developer retrieval can search all indexed topic files when selection is empty (`web/files.py:181–198`). An interface-only CV label therefore does not establish an evidence boundary.

**Alternatives considered:** Explicit designation of an existing topic file; dedicated topic-scoped CV resource; application-wide CV/profile with explicit topic grants.

**Recommendation/rationale:** Begin with a dedicated versioned topic-scoped CV-purpose resource. Existing-file reuse requires explicit designation and a decision about retaining its study/index role. Never infer CV eligibility from filename, terminology or attachment selection. Dedicated acquisition can reuse parsing without embeddings/study retrieval. Global reuse would introduce an absent cross-topic access/lifecycle contract.

**Tradeoff/open decision:** Topic scope may require repeated provision/designation; global scope reduces duplication but broadens access. Design/user must settle scope. Reconsider topic-only storage if the user explicitly wants a reusable application-wide CV with defined topic grants.

## Acquisition, extraction, correction and removal

**Verified:** Current upload routes accept only PDF and check extension/header (`web/files.py:62–71`). Docling adapter restricts input to PDF and explicitly disables OCR (`docling_pipeline.py:67–79`). Installed Docling is 2.127.0, docling-core 2.98.0. A read-only installed-package probe found library default do_ocr=True, while the app overrides False. Scanned CV support is therefore unproven; the adapter asks for searchable PDF when OCR is needed (`docling_pipeline.py:215–223`). Library format support is broader than app support: [Docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/).

**Alternatives:** Searchable PDF; explicitly pasted actual CV text as a CV document; new DOCX/scanned-PDF adapters. A skill questionnaire is not a CV replacement.

**Recommendation/rationale:** Searchable PDF is the smallest compatible first path. Pasted CV text is credible only if the user accepts it as supplying a CV. Do not silently add DOCX/OCR. Preview extracted text and warnings: nonempty output does not prove a two-column CV was read correctly. A sparse readable CV can qualify; missing skill evidence means not evidenced, not unfamiliar.

Distinguish original preservation, active-version replacement, correction/user clarification, revocation of future personalization, and physical erasure. There is no file-deletion route; topic DELETE archives metadata and retains files (`web/topics.py:45–52`). Remove CV must not promise deletion it does not perform. Historical provenance helps inspection, but revocation does not erase old imported context or retained artifacts.

**Next validation/owner:** Design settles formats/removal semantics; code/usage exercise synthetic multi-column, scanned, empty, partial and corrected CVs. Broaden formats only for demonstrated need and adapter validation.

## What prerequisite proposals claim

**Verified:** Canonical section units retain text, tables, formula text, refs and pages. Figure pixels are excluded; captions are included (`document_map.py:68–89`). section_sources selects complete saved scope (`section_summary.py:208–242`). Identity depends on original/native revisions (`document_map.py:36–48`; `document_map_store.py:267–301`). A saved generated summary is not needed as input.

**Alternatives:** Summary+CV; canonical complete section+CV; top-k retrieval or entire paper for broader dependencies.

**Recommendation/rationale:** Use complete selected-section source and descendants directly plus eligible CV, avoiding another lossy generated-summary layer. Each candidate separates a broad requirement, why it matters here (labeled inference with section references), CV relationship (directly mentioned/related/not evidenced with CV refs), and the app-supplied individual comfort question.

Example: Basic Python may matter for reproducing computations. The CV mentions Python but does not prove current comfort; the app still asks whether comfortable with basic Python. Bind excerpts from actual referenced source units rather than model-authored quotations. Valid reference membership is provenance, not entailment or exhaustive pedagogy.

Do not infer unfamiliarity from omission, mastery from a degree/job title, or coding requirements for a reading-only goal. Declare dependencies beyond section scope as gaps. Design defines granularity; synthetic human-reviewed quality cases compare reading/reproduction intent, direct/related CV evidence and omissions. Broader source scope requires demonstrated selected-section failures.

## Structured output through the same model gateway

**Verified:** ModelGateway.stream_chat has no structured-output parameter (`contracts.py:153–162`); models.py sends messages, streaming, keep_alive:0 and budgets but no format (`models.py:137–194`). It verifies installed local models and refuses remote/cloud models. Ollama documents JSON/schema format: [chat API](https://docs.ollama.com/api/chat), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs).

**Alternatives:** Prompt-only JSON through unchanged gateway; optional schema argument on existing gateway; separate structured client/service.

**Recommendation/rationale:** A narrow optional schema parameter on the existing gateway, preserving ordinary chat/summary defaults, local verification, lock, cancellation and errors. No new framework/second model service is justified. Buffer JSON until provider completion; parse/validate fields and references before durable publication. Partial JSON is not actionable. Invalid/missing output fails visibly without automatic repair inference. Comfort questions are deterministic app output for EVERY validated item.

Fresh messages establish request independence; keep_alive controls residency, not conversation separation. API documentation establishes capability, but installed daemon/model/thinking compatibility was NOT tested. Valid shape cannot prove good prerequisites.

**Next gate:** Fake HTTP proves optional schema payload and unchanged defaults; isolated selected-model spike tests small schema/thinking/malformed/refusal/length behavior. Prefer validated prompt-only fallback only after concrete incompatibility evidence.

## Goal, complete input budget and freshness

**Verified:** Chat includes topic goal as context (`chat_prompt.py:44–47`); summaries omit it. Neither settles prerequisites. Existing estimator uses one estimated token per UTF-8 byte and reserves up to 2,048 output tokens (`context.py:10–34`). Summary preflight refuses complete oversized prompts (`section_summary.py:149–161`); explicit context metadata bypasses ordinary trimming (`models.py:148–157`).

**Synthetic probe:** A complete synthetic policy/section/CV prompt measured 10,326 estimated input tokens; with 2,048 reserve it failed 8,192 context and fit 32,768. This is not a real CV/paper or actual token count.

**Alternatives:** Complete source+CV/refuse overflow; top-k retrieval; cached generated learner profile or shortened CV.

**Recommendation/rationale:** Start with complete eligible evidence and fresh policy, refusing overflow rather than silently omitting CV/source. Compact profiles/retrieval need separate coverage/correction/provenance contracts. Include optional topic goal as clearly labeled context: reading versus implementation changes preparation. Missing goal is not another gate; proposed visible default is understand this section.

Dependencies include section/source revision, CV-purpose/extraction/correction versions, goal snapshot, prompt/schema and relevant model settings; responses need their own version. Changes/revocation make prior proposals historical. Conservative estimates can reject otherwise fitting input and repeat CV cost; neither justifies hidden truncation. Design/user settle goal use; code verifies invalidation/preflight, real-model spike output reserve. Reconsider compact profiles after measured recurring fit failures.

## Per-requirement familiarity and refinement

**Verified:** No prerequisite/comfort records exist. Ordinary history projects role/content/thinking (`chat_session.py:22–30`); browser selected files are not a durable learner profile (`hooks/useTopicSession.ts:48–55`).

**Alternatives:** Chat-only records; per-assessment/requirement records; global skill/mastery profile.

**Recommendation/rationale:** Persist exact assessment/requirement responses: comfortable, needs refresher, new to me, not sure, plus optional clarification and editing. Self-report is not measured mastery. Each new requirement gets its own pending question even with strong CV evidence or similarly named earlier requirements. No transfer by text similarity. Server-owned requirement text and response-version checks under topic lease prevent stale writes.

**Refinement alternatives:** Model call after each answer; explicit batch revise-list call; compact existing-main-chat handoff. Recommend collecting answers then explicitly continuing in main chat, avoiding automatic per-answer inference. If a revised list is required before handoff, make batch revision explicit. Interaction placement remains a product choice and must preserve feedback-driven refinement. Global skill memory is outside this increment.

**Next owner/gates:** Design/user settle placement and pending-answer handoff. Code tests reload/correction/concurrent writes/new-requirement questions.

## Main conversation and source honesty

**Verified:** Existing summary import validates destination, copies server-owned content, uses atomic conversation-local idempotency and no inference (`web/summary_imports.py:20–66`). Actual content labels generated context (`summary_import.py:89–94`).

**Alternatives:** Labeled snapshot+ordinary chat; auto-send refinement prompt; full CV in every future chat.

**Recommendation/rationale:** Reuse the pattern with distinct prerequisite-context schema, not semantically false summary_import metadata. Snapshot carries section/source identity, requirements/rationale, every answer or explicitly pending state, concise relevant CV evidence distinguished from self-report, and assessment/CV/answer versions. Capture selected existing destination, import once per snapshot/version, focus main conversation; optional draft prompt, never automatic send or new chat. Avoid whole-CV import by default.

Imported context receives ordinary budgeting. Synthetic probe confirmed long imported content can be shortened while durable original stays intact (`context.py:37–49,104–124`). Display metadata does not reach model; concise provenance/self-report distinctions must appear in actual message content. Permanent automatic injection would require another explicit contract. Design owns wording; code/usage verify default/named destination, retries, changed answer versions, reload and subsequent normal chat.

## Module and lifecycle boundaries

Reuse safe topic/file resolution and atomic JSON (`storage.py:21–68,117–162`), topic leases/shared generation lock (`web/locks.py:38–63`, `web/deps.py:28–47`), fresh policy failure (`runtime_policy.py:8–18`), workspace lifecycle/captured IDs (`hooks/useSectionSummary.ts:81–129,139–169,230–279`), shared activity/wire schemas and source-page honesty (`components/DocumentMapPanel.tsx:348–368`).

New responsibilities: CV-purpose acquisition/versioning, pure prerequisite planning/validation, assessment storage, self-reports, prerequisite-context handoff. Keep learner-dependent state separate from strict native map schema (`document_map_store.py:44–87`). Opening/selecting/uploading CV/saving answers should not invoke the learning model. No background course engine.

## Prioritized decisions for design and user

1. Topic CV versus reusable application CV with explicit access.
2. Searchable PDF only versus accepted pasted actual CV text.
3. Answer each requirement then main-chat refinement versus an explicit pre-handoff list revision.
4. Optional topic goal with visible understand-this-section default.
5. Revocation versus retained-material erasure, or distinct actions for both.
6. Every item answered (not sure allowed) versus explicitly pending items in handoff.

These do not reopen mandatory CV, same model, EVERY-item familiarity or main-chat-only depth.

## Validation and limits

Code: missing/ineligible/cross-topic CV blocks with zero model calls; extraction correction/replacement/revocation/history; complete policy/evidence budget before save/model; no trimming/retrieval; lock/cancellation/EOF/length/save errors; optional schema doesn't alter chat/summary defaults; no partial actionable cards; EACH-item checks, answer corrections/reload/concurrency and no implicit transfer; captured idempotent main-chat handoff and normal follow-up.

Research/usage quality spike: human-check source grounding, CV omission versus unfamiliarity, CV mention versus comfort, reading versus implementation intent, and high/medium depth. Schema checks alone cannot establish these.

Performed: repository/adapter/schema/UI inspection; official Ollama/Docling docs; installed versions/defaults; synthetic budget/history probes; focused context/model/runtime-policy/summary tests 48 passed plus 13 subtests, two dependency deprecations. No real CV parsing, personal data, actual Ollama schema generation, new-feature browser flow, pedagogical quality test, full build or implementation occurred. Local evidence sufficed for storage/locks/policy/handoff; broad framework research was unnecessary. Design is next after coordinator delivery and saving.
