# Research, design and implementation reports

Organized by feature on 12 October 2026. Feature folder names contain no more than three words, written as lowercase hyphenated slugs. Dated filenames and original/regenerated comparisons are preserved.

## Durable reports

| Feature folder | Saved records |
| --- | --- |
| [Document Map](document-map/) | [Original consolidated research/design plan](document-map/2026_10_05_document_map_plan.md), [regenerated plan](document-map/2026_10_05_document_map_plan_regenerated.md), [implementation decisions and validation](document-map/2026_10_05_document_map_implementation.md) |
| [Personalized Prerequisites](personalized-prerequisites/) | Separate [research](personalized-prerequisites/2026_10_12_personalized_prerequisites_research.md) and [design](personalized-prerequisites/2026_10_12_personalized_prerequisites_design.md) reports, plus [consolidated plan](personalized-prerequisites/2026_10_12_personalized_prerequisites_plan.md) and [12 October implementation checkpoints](personalized-prerequisites/2026_10_12_personalized_prerequisites_implementation.md) and [13 October continuation](personalized-prerequisites/2026_10_13_personalized_prerequisites_implementation.md) |
| [Evidence Retrieval](evidence-retrieval/) | Separate [research](evidence-retrieval/2026_10_15_evidence_retrieval_research.md) and [design](evidence-retrieval/2026_10_15_evidence_retrieval_design.md), plus [consolidated discussion/decisions](evidence-retrieval/2026_10_15_evidence_retrieval_discussion.md); [16 October implementation checkpoints](evidence-retrieval/2026_10_16_evidence_retrieval_implementation.md) and [18 October continuation](evidence-retrieval/2026_10_18_evidence_retrieval_implementation.md) and [19 October continuation](evidence-retrieval/2026_10_19_evidence_retrieval_implementation.md) |
| [Architecture](architecture/) | [Architecture research/review and refactor proposals](architecture/architecture-review.md) |
| [Conversations](conversations/) | [Multi-conversation review, implementation and verification](conversations/2026_10_03_resume_validation.md) |
| [Retrieval Evaluation](retrieval-evaluation/) | [Three-paper methodology and validation](retrieval-evaluation/retrieval_eval_validation.md) |
| [Parser Skills](parser-skills/) | [Parser-skill provenance and review](parser-skills/skills-review.md) |
| [Foundation](foundation/) | [Initial foundation validation and follow-ups](foundation/validation.md) |

These are 19 durable reports. Current API/architecture/engineering documentation stays at its canonical location. Additional combined decision/validation material remains in [runtime policy](../runtime_policy.md) and [query traces](../query_traces.md).

## Older local reports

Twenty-five raw research, review, design, usage and stocktake reports are organized under ignored `.local/verification/reports/`, with their own `README.md` index. Feature folders: `conversations`, `engineering-policy`, `ingestion`, `project-roadmap`, `query-traces`, `retrieval-evaluation`, `runtime-policy`, and `workspace-verification`.

This includes the three paper-specific research reports, runtime-policy design/review, ingestion reviews, conversation/trace reviews and older usage evidence. Originals' related logs, PDFs, fixture policies and extraction artifacts stay in the source verification directories; relocation notes identify them. Raw/local reports are not added to Git. Copies inside older worktrees are not treated as additional canonical reports.

## Completeness and history

Not every historical agent response was saved as a separate file. The Document Map's original research/design messages were synthesized into its consolidated plans; the newer prerequisite reports are separately saved coordinator records. Earlier completed handoff/task-brief files were removed on 3 October at Tanmay's request, as recorded in the R1 snapshot; tracked versions remain in Git history and were not recreated. This index lists reports currently present rather than inventing missing originals.

## Filing future reports

Save dated feature research/design reports and consolidated decision notes in `docs/reports/<feature>/`, and add them here. Use a feature name of at most three words. Explain whether role findings are separate reports or consolidated; preserve earlier dated versions. Keep raw/local evidence under ignored `.local/verification/reports/<feature>/`, with pointers to its original run artifacts.

Former report locations contain short location notices so links in earlier chats and external project notes continue to resolve. Report bodies live only in the feature folders.
