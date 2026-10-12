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
