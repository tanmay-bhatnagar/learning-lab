# Personalized prerequisites — research and design discussion

Date: 12 October 2026. Status: planning only; application implementation is not authorized by this task. Coordinator owns this consolidated decision note and Git; research/design are read-only and run sequentially to completion.

## Settled user requirements

- The feature is on demand and uses the same selected local Ollama model.
- A CV supplied for this purpose is mandatory. If unavailable, ask for it and block this feature; do not replace the requirement with a questionnaire-only path.
- Use the CV to tailor high/medium-level learning requirements. A requirement such as basic Python must not expand into a library-by-library syllabus.
- The CV describes experience, not demonstrated mastery. EACH requirement asks whether the user is already comfortable with it; there is no single familiarity question for the entire list.
- User feedback guides refinement. Deeper discussion or a course can develop in the existing main conversation; no side conversation or autonomous course-generation workflow is implied.
- Preserve separate cohesive modules, explicit dependencies, runtime policy/context boundaries, topic isolation, originals and clear generated-content provenance.

## Investigation order and deliverables

Research runs first under the repository research skill, tracing the current code and validating material external technical uncertainty with primary sources as needed. After its final report is saved and explained, design receives that evidence and proposes observable behavior, contracts, module ownership, compatibility, lifecycle, verification and implementation slices. Both finish naturally without interruption. No application edits, personal CV/topic access, model downloads, remote pushes or releases are included.

Two separate role reports will be preserved alongside this consolidated note: `2026_10_12_personalized_prerequisites_research.md` and `2026_10_12_personalized_prerequisites_design.md`. This note distinguishes user-set requirements from agent recommendations and still-open discussion questions.

## Decisions to investigate, not yet settled

CV acquisition/reuse and authorized scope; what qualifies as a usable CV; replacement/removal and stale results; learner feedback meanings, persistence and whether familiarity checks appear together or sequentially; grounding/provenance and output depth; learning-goal influence; integration with main chat; prompt budget, model-format reliability and failure behavior. Research/design must explain credible alternatives, rationale/tradeoffs, verified versus untested claims, next validation owner and conditions that would change the recommendation.

## Research checkpoint — completed before design

Research (Sol High) recommends explicit CV-purpose storage rather than filename/attachment inference: current study uploads are indexed and empty-selection developer retrieval can search the topic index. Topic scope is the smallest fit; global reuse needs a new explicit access/lifecycle contract. This is a recommendation for discussion, not a user choice already made. Complete native section source plus CV avoids a lossy generated-summary input. Each familiarity question should be supplied by the app itself, preserving the EVERY-item invariant independently of model output.

The gateway currently lacks Ollama's documented structured-output argument; a narrow optional schema parameter is preferred over a second model client/framework. Installed-model/daemon compatibility and pedagogical quality remain untested. A synthetic complete-input budget exceeded 8,192 but fit 32,768, so silently dropping background/source is not an acceptable cost workaround. Forty-eight focused existing tests plus 13 subtests passed; no real CV/model call or implementation occurred.

The [separate research report](2026_10_12_personalized_prerequisites_research.md) preserves alternatives, references, findings and limits. Design next settles candidate contracts for scope/formats/refinement/goal/removal/pending answers, distinguishing recommended defaults from choices needing user discussion. Earlier Document Map history remains untouched.

## Design checkpoint — completed without interruption

Design (Sol Medium) finished after research and used its evidence; no new experiments or application edits. The [separate design report](2026_10_12_personalized_prerequisites_design.md) proposes contracts, module ownership, milestones and validation gates. Neither role was interrupted.

Recommended feedback flow: all requirement cards together, EACH independently questioned and editable. Answers are self-reports: comfortable lowers preparation priority, refresher suggests short review, new suggests foundations, uncertain asks clarification, unanswered remains pending. Saving them causes no inference. Explicit versioned handoff to the selected existing main conversation supplies refinement context; an editable draft is not automatically sent. This is simpler/cheaper than per-answer model calls and keeps deeper course discussion in ordinary chat. No global skill/mastery profile or forced all-answered gate is recommended.

The app must supply EVERY familiarity question deterministically, bind requirements to original section evidence and CV refs, buffer structured generation until provider completion/validation/save, and keep learner-dependent assessment/answer versions separate from native map state. Complete inputs and fresh runtime policy use the existing shared local gateway; optional schema support is recommended over a separate client/framework. Local compatibility and pedagogical quality remain open, with an isolated synthetic spike as the first technical validation step. No ready-feature claim is justified yet.

Two pending user choices: topic CV versus reusable workstation CV with explicit topic access, and searchable PDF only versus also accepting pasted actual CV text. Topic scope/PDF-only are role recommendations for the smallest first version, not silent settled choices. Proposed defaults also need discussion: visible optional topic goal with reading default, pending answers allowed, main-chat refinement and revoke-future-use rather than erasure. Revocation preserves originals and historical imported context; it must not be labeled delete/forget. Global reuse or physical erasure changes require explicit revised contracts.

Planning work uses no personal CV. Application implementation remains unstarted pending discussion/authorization. Two role reports are separate; this plan is the consolidated synthesis. Earlier dated plans and implementation notes remain preserved.
