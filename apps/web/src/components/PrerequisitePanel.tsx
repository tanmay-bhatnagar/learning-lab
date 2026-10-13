import { Sparkles, Square } from 'lucide-react';
import { useState } from 'react';
import type { PrerequisiteAssessment, PrerequisiteAttempt } from '../api/prerequisites';
import type { MapSourceUnit } from '../api/documentMap';
import type { ProficiencyEntryView } from '../domain/proficiency';
import { originalPdfUrl } from '../api/urls';
import { RequirementAnswers } from './RequirementAnswers';
import { RichText } from './RichText';
import './prerequisite.css';

type Props = {
  topicId: string;
  fileId: string;
  fileName: string;
  sectionId: string;
  sectionTitle: string;
  pageCount?: number | null;
  units: MapSourceUnit[];
  proficiencyEntries: ProficiencyEntryView[];
  proficiencyError: string;
  proficiencySaving: boolean;
  assessment: PrerequisiteAssessment | null;
  assessmentStaleReason: string;
  attempt: PrerequisiteAttempt | null;
  loading: boolean;
  running: boolean;
  progress: string;
  error: string;
  blockedReason: string;
  modelName: string;
  busy: boolean;
  defaultGoal: string;
  onGenerate: (goal: string) => void;
  onStop: () => void;
  onReload: () => void;
  onOpenMyProficiency: () => void;
  onSaveProficiency: (drafts: ProficiencyEntryView[]) => void | Promise<void>;
  onReloadProficiency: () => void | Promise<void>;
  mainChatTitle: string;
  canImportAssessment: boolean;
  canDraftFollowUp: boolean;
  importing: boolean;
  importNotice: string;
  importError: string;
  preferenceLoading: boolean;
  preferenceError: string;
  onReloadPreference: () => void;
  onAddToMainChat: () => void | Promise<void>;
  onDraftFollowUp: () => void;
};

export function PrerequisitePanel({
  topicId,
  fileId,
  fileName,
  sectionId,
  sectionTitle,
  pageCount,
  units,
  proficiencyEntries,
  proficiencyError,
  proficiencySaving,
  assessment,
  assessmentStaleReason,
  attempt,
  loading,
  running,
  progress,
  error,
  blockedReason,
  modelName,
  busy,
  defaultGoal,
  onGenerate,
  onStop,
  onReload,
  onOpenMyProficiency,
  onSaveProficiency,
  onReloadProficiency,
  mainChatTitle,
  canImportAssessment,
  canDraftFollowUp,
  importing,
  importNotice,
  importError,
  preferenceLoading,
  preferenceError,
  onReloadPreference,
  onAddToMainChat,
  onDraftFollowUp,
}: Props) {
  const [goal, setGoal] = useState(defaultGoal || `Understand “${sectionTitle}”`);
  const unitById = new Map(units.map((unit) => [unit.id, unit]));
  const hasNoCv = /CV/i.test(blockedReason);

  return (
    <section className="prerequisite-panel" aria-labelledby="prerequisite-panel-title">
      <header className="prerequisite-header">
        <div>
          <span className="eyebrow">ON-DEMAND PREREQUISITES</span>
          <h3 id="prerequisite-panel-title">{sectionTitle || 'Choose a section'}</h3>
          <p className="muted">Generate a high-level learning checklist for this section and its nested sections.</p>
        </div>
        {running ? (
          <button className="text-button" onClick={onStop}>
            <Square size={14} /> Stop
          </button>
        ) : (
          <button
            className="primary"
            disabled={!sectionId || busy || !!blockedReason || !goal.trim() || goal.length > 2000}
            onClick={() => onGenerate(goal.trim())}
          >
            <Sparkles size={15} /> {assessment ? 'Regenerate prerequisites' : 'Generate prerequisites'}
          </button>
        )}
      </header>

      {sectionId && (
        <label className="prerequisite-goal">
          What do you want from this section?
          <textarea
            value={goal}
            maxLength={2000}
            rows={2}
            disabled={busy}
            onChange={(event) => setGoal(event.target.value)}
          />
        </label>
      )}
      <p className="muted prerequisite-model">
        Uses {modelName || 'the model selected in Settings'} with the CV selected in My proficiency. Nothing is
        generated until you choose this button.
      </p>

      {loading && (
        <p className="prerequisite-status" role="status">
          Loading saved prerequisite state…
        </p>
      )}
      {blockedReason && !loading && (
        <div className="prerequisite-blocked" role="status">
          <span>{blockedReason}</span>
          {hasNoCv && (
            <button className="text-button" onClick={onOpenMyProficiency}>
              Open My proficiency
            </button>
          )}
          {error && (
            <button className="text-button" disabled={busy} onClick={onReload}>
              Reload
            </button>
          )}
        </div>
      )}
      {running && (
        <p className="prerequisite-status" role="status">
          {progress || 'Generating prerequisite assessment…'}
        </p>
      )}
      {error && !blockedReason && (
        <p className="prerequisite-error" role="alert">
          {error}
        </p>
      )}
      {!running && attempt && ['error', 'cancelled', 'interrupted'].includes(attempt.status) && (
        <p className="prerequisite-warning">
          Previous attempt: {attempt.status}. Its text is not shown as a saved assessment.
        </p>
      )}
      {assessment && !running && (
        <article className="prerequisite-assessment">
          {assessmentStaleReason && <p className="prerequisite-warning">Historical result: {assessmentStaleReason}</p>}
          <div className="prerequisite-overview">
            <strong>Learning requirements</strong>
            <p>{assessment.overview}</p>
            <small>
              {assessment.requirements.length === 0
                ? 'CV evidence was not assessed because this result identified no prerequisite concepts.'
                : `CV background for these proposed concepts: ${assessment.requirements.some((requirement) => requirement.cv_background === 'mentioned') ? 'the CV mentions relevant experience; this is not a proficiency rating.' : 'no relevant experience was stated for these concepts in the CV.'}`}
            </small>
          </div>
          {assessment.requirements.map((requirement) => (
            <section className="prerequisite-requirement" key={requirement.requirement_id}>
              <h4>{requirement.concept}</h4>
              <RichText text={requirement.reason} />
              <p className="prerequisite-question">{requirement.question}</p>
              <div className="prerequisite-citations">
                <strong>Sources</strong>
                {requirement.source_labels.map((label) => {
                  const source = assessment.sources.find((item) => item.label === label);
                  const unit = source ? unitById.get(source.unit_id) : undefined;
                  const pages = (source?.pages ?? []).filter((page) => pageCount == null || page <= pageCount);
                  return (
                    <div className="prerequisite-citation" key={label}>
                      <span>
                        [{label}] {unit?.text || 'Source preview unavailable.'}
                      </span>
                      {pages.map((page) => (
                        <a key={page} href={originalPdfUrl(topicId, fileId, page)} target="_blank" rel="noreferrer">
                          Page {page}
                        </a>
                      ))}
                    </div>
                  );
                })}
              </div>
              {requirement.cv_background === 'mentioned' && (
                <blockquote className="prerequisite-cv-quote">“{requirement.cv_quote}” [CV1]</blockquote>
              )}
            </section>
          ))}
          {assessment.requirements.length === 0 && (
            <p className="muted">No prerequisite topics were identified for this section.</p>
          )}
          <RequirementAnswers
            key={`${assessment.topic_id}:${assessment.assessment_id}`}
            assessment={assessment}
            sectionTitle={sectionTitle}
            fileName={fileName}
            entries={proficiencyEntries}
            busy={busy || running}
            saving={proficiencySaving}
            profileError={proficiencyError}
            onSave={onSaveProficiency}
            onReload={onReloadProficiency}
          />
          <div className="prerequisite-main-chat-actions">
            <button
              className="secondary"
              type="button"
              disabled={!canImportAssessment || busy || running || importing}
              onClick={() => void onAddToMainChat()}
            >
              {importing ? 'Adding…' : `Add to “${mainChatTitle}”`}
            </button>
            <button
              className="text-button"
              type="button"
              disabled={!canDraftFollowUp || busy || running}
              onClick={onDraftFollowUp}
            >
              Draft a follow-up
            </button>
            {preferenceLoading && (
              <p className="muted" role="status">
                Loading the current conversation preference…
              </p>
            )}
            {preferenceError && (
              <div className="prerequisite-error" role="alert">
                <span>{preferenceError}</span>
                <button className="text-button" type="button" disabled={busy} onClick={onReloadPreference}>
                  Reload conversation preference
                </button>
              </div>
            )}
            {importNotice && (
              <p className="success" role="status">
                {importNotice}
              </p>
            )}
            {importError && (
              <p className="prerequisite-error" role="alert">
                {importError}
              </p>
            )}
          </div>
          <p className="muted prerequisite-cv-note">CV1 refers to the selected CV used for this assessment.</p>
        </article>
      )}
    </section>
  );
}
