import { useMemo, useState } from 'react';
import type { PrerequisiteAssessment } from '../api/prerequisites';
import type { ProficiencyDraft, ProficiencyEntryView } from '../domain/proficiency';
import './proficiency.css';
import './prerequisite.css';

type Props = {
  assessment: PrerequisiteAssessment;
  sectionTitle: string;
  fileName: string;
  entries: ProficiencyEntryView[];
  busy: boolean;
  saving: boolean;
  profileError: string;
  onSave: (drafts: ProficiencyDraft[]) => void | Promise<void>;
  onReload: () => void | Promise<void>;
};

const choices = [
  { value: '', label: 'Choose one…' },
  { value: 'comfortable', label: 'Comfortable' },
  { value: 'refresher', label: 'Needs a refresher' },
  { value: 'new', label: 'New to me' },
  { value: 'unsure', label: 'Not sure' },
] as const;

export function RequirementAnswers({
  assessment,
  sectionTitle,
  fileName,
  entries,
  busy,
  saving,
  profileError,
  onSave,
  onReload,
}: Props) {
  const initial = useMemo(
    () =>
      assessment.requirements.map((requirement) => {
        const matching = entries.filter(
          (entry) =>
            entry.kind === 'requirement' &&
            entry.concept === requirement.concept &&
            entry.requirementId === requirement.requirement_id &&
            entry.topicId === assessment.topic_id &&
            entry.assessmentId === assessment.assessment_id,
        );
        const saved = matching.length === 1 ? matching[0] : undefined;
        const draft: ProficiencyDraft = {
          id: saved?.id ?? `requirement:${assessment.assessment_id}:${requirement.requirement_id}`,
          concept: requirement.concept,
          comfort: saved?.comfort ?? '',
          note: saved?.note ?? '',
          kind: 'requirement',
          requirementId: requirement.requirement_id,
          topicId: assessment.topic_id,
          assessmentId: assessment.assessment_id,
        };
        return { requirement, draft, rowAvailable: matching.length === 1, ambiguous: matching.length > 1 };
      }),
    [assessment, entries],
  );
  const [edits, setEdits] = useState<Record<string, ProficiencyDraft>>({});
  const [savePending, setSavePending] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saveNotice, setSaveNotice] = useState('');
  const drafts = initial.map((item) => ({ ...item, draft: edits[item.requirement.requirement_id] ?? item.draft }));
  const changed = drafts.filter((item) => !!edits[item.requirement.requirement_id]);
  const canSave =
    changed.length > 0 &&
    changed.every((item) => item.rowAvailable) &&
    !profileError &&
    !busy &&
    !saving &&
    !savePending;

  const update = (draft: ProficiencyDraft) => {
    setEdits((current) => ({ ...current, [draft.requirementId ?? draft.id]: draft }));
    setSaveError('');
    setSaveNotice('');
  };

  const submit = async () => {
    if (!canSave) return;
    setSavePending(true);
    setSaveError('');
    setSaveNotice('');
    try {
      await onSave(changed.map((item) => item.draft));
      setEdits({});
      setSaveNotice('Your answers were saved to My proficiency.');
    } catch (reason) {
      setSaveError(
        reason instanceof Error ? reason.message : 'Could not save these answers. Your edits are still here.',
      );
    } finally {
      setSavePending(false);
    }
  };

  if (assessment.requirements.length === 0) return null;

  return (
    <section className="requirement-answers" aria-label="Requirement answers">
      <header>
        <strong>My proficiency</strong>
        <p className="muted">
          {sectionTitle} · {fileName}
        </p>
        <p className="muted">
          These are your self-reports. The model’s suggestions and CV evidence do not fill them in.
        </p>
      </header>
      {drafts.map(({ requirement, draft, rowAvailable, ambiguous }) => (
        <article className="proficiency-card" key={requirement.requirement_id}>
          <div className="proficiency-card-heading">
            <div>
              <h4>{requirement.concept}</h4>
              <p>{requirement.reason}</p>
            </div>
            <span className="proficiency-source">Model suggestion</span>
          </div>
          <p className="prerequisite-question">{requirement.question}</p>
          <label className="proficiency-field">
            Your comfort with {requirement.concept}
            <select
              aria-label={`Your comfort with ${requirement.concept}`}
              value={draft.comfort}
              disabled={!rowAvailable || !!profileError || busy || saving || savePending}
              onChange={(event) => update({ ...draft, comfort: event.target.value as ProficiencyDraft['comfort'] })}
            >
              {choices.map((choice) => (
                <option key={choice.value || 'pending'} value={choice.value}>
                  {choice.label}
                </option>
              ))}
            </select>
          </label>
          <label className="proficiency-field">
            Notes for {requirement.concept}
            <textarea
              aria-label={`Notes for ${requirement.concept}`}
              value={draft.note}
              maxLength={240}
              rows={2}
              disabled={!rowAvailable || !!profileError || busy || saving || savePending}
              onChange={(event) => update({ ...draft, note: event.target.value })}
            />
          </label>
          {!rowAvailable && (
            <div className="prerequisite-warning" role="status">
              {ambiguous
                ? 'More than one saved proficiency row matches this requirement. Reload My proficiency before editing.'
                : 'This requirement has no matching saved proficiency row yet. Reload My proficiency before editing.'}
            </div>
          )}
          <small className="muted">
            CV evidence:{' '}
            {requirement.cv_background === 'mentioned' ? 'relevant experience was mentioned' : 'not stated'}.
            {requirement.cv_background === 'mentioned' && requirement.cv_quote ? ` “${requirement.cv_quote}”` : ''}
          </small>
        </article>
      ))}
      <div className="prerequisite-answer-actions">
        <button className="primary" type="button" disabled={!canSave} onClick={() => void submit()}>
          {saving || savePending ? 'Saving…' : 'Save proficiency'}
        </button>
        {!canSave && changed.length === 0 && <span className="muted">Choose an answer or add a note, then save.</span>}
        {(drafts.some((item) => !item.rowAvailable) || !!profileError) && (
          <button className="text-button" type="button" disabled={busy || saving || savePending} onClick={onReload}>
            Reload proficiency
          </button>
        )}
      </div>
      {profileError && (
        <p className="prerequisite-error" role="alert">
          {profileError}
        </p>
      )}
      {saveError && (
        <p className="prerequisite-error" role="alert">
          {saveError}
        </p>
      )}
      {saveNotice && (
        <p className="success" role="status">
          {saveNotice}
        </p>
      )}
    </section>
  );
}
