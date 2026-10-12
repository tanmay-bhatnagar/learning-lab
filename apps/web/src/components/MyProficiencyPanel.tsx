import { useMemo, useRef, useState } from 'react';
import {
  createRequirementDraft,
  hasDuplicateConcept,
  mergeRefreshedDrafts,
  type ComfortAnswer,
  type CvView,
  type ProficiencyDraft,
  type ProficiencyEntryView,
  type RequirementView,
} from '../domain/proficiency';
import './proficiency.css';

export type MyProficiencyPanelProps = {
  requirements: RequirementView[];
  entries: ProficiencyEntryView[];
  cvs: CvView[];
  selectedCvId: string;
  activeConversationId: string;
  includeCv: boolean;
  busy: boolean;
  saving: boolean;
  error: string;
  notice: string;
  onSave: (drafts: ProficiencyDraft[]) => void | Promise<void>;
  onUploadCv: (file: File, filename: string) => void | Promise<void>;
  onSelectCv: (id: string) => void;
  onRevokeCv: (id: string) => void;
  onIncludeCvChange: (include: boolean) => void;
};

const comfortOptions: { value: ComfortAnswer; label: string }[] = [
  { value: '', label: 'Choose one…' },
  { value: 'comfortable', label: 'Comfortable' },
  { value: 'refresher', label: 'Needs a refresher' },
  { value: 'new', label: 'New to me' },
  { value: 'unsure', label: 'Not sure' },
];

function ComfortSelect({
  concept,
  value,
  disabled,
  onChange,
}: {
  concept: string;
  value: ComfortAnswer;
  disabled: boolean;
  onChange: (value: ComfortAnswer) => void;
}) {
  return (
    <label className="proficiency-field">
      Your comfort with {concept}
      <select
        aria-label={`Your comfort with ${concept}`}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as ComfortAnswer)}
      >
        {comfortOptions.map((option) => (
          <option key={option.value || 'pending'} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function MyProficiencyPanel({
  requirements,
  entries,
  cvs,
  selectedCvId,
  activeConversationId,
  includeCv,
  busy,
  saving,
  error,
  notice,
  onSave,
  onUploadCv,
  onSelectCv,
  onRevokeCv,
  onIncludeCvChange,
}: MyProficiencyPanelProps) {
  const initialDrafts = useMemo(
    () => [
      ...entries.map((entry) => ({ ...entry })),
      ...requirements
        .filter((requirement) => !entries.some((entry) => entry.requirementId === requirement.id))
        .map((requirement) => createRequirementDraft(requirement, entries)),
    ],
    [entries, requirements],
  );
  const [drafts, setDrafts] = useState<ProficiencyDraft[]>([]);
  const [newConcept, setNewConcept] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [filename, setFilename] = useState('');
  const [uploadPending, setUploadPending] = useState(false);
  const [savePending, setSavePending] = useState(false);
  const [panelError, setPanelError] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const saveInFlight = useRef(false);
  const visibleDrafts = mergeRefreshedDrafts(
    drafts,
    initialDrafts,
    requirements.map(({ id }) => id),
  );
  const selectedCv = cvs.find((cv) => cv.id === selectedCvId);
  const canIncludeCv = !!activeConversationId && selectedCv?.status === 'ready' && !!selectedCv.extractedText;
  const canUpload = !!selectedFile && !!filename.trim() && !busy && !uploadPending;

  const updateDraft = (id: string, update: Partial<ProficiencyDraft>) => {
    if (busy || saving || savePending || saveInFlight.current) return;
    setDrafts((current) => {
      const source = current.find((draft) => draft.id === id) ?? visibleDrafts.find((draft) => draft.id === id);
      if (!source) return current;
      return [...current.filter((draft) => draft.id !== id), { ...source, ...update }];
    });
  };

  const addSkill = () => {
    if (busy || saving || savePending || saveInFlight.current) return;
    const concept = newConcept.trim();
    if (!concept || hasDuplicateConcept(concept, visibleDrafts)) {
      setPanelError(
        concept ? 'That skill is already listed. Edit its existing entry instead.' : 'Enter a skill or concept first.',
      );
      return;
    }
    const nextDraft: ProficiencyDraft = {
      id: `manual:${crypto.randomUUID()}`,
      concept,
      comfort: '',
      note: '',
      kind: 'manual',
    };
    setDrafts((current) => [...current, nextDraft]);
    setNewConcept('');
    setPanelError('');
  };

  const submitProficiency = async () => {
    if (busy || saving || savePending || saveInFlight.current) return;
    saveInFlight.current = true;
    setSavePending(true);
    setPanelError('');
    try {
      await onSave(visibleDrafts);
      setDrafts([]);
    } catch (cause) {
      setPanelError(cause instanceof Error ? cause.message : 'Could not save proficiency. Your edits are still here.');
    } finally {
      saveInFlight.current = false;
      setSavePending(false);
    }
  };

  const submitCv = async () => {
    if (!selectedFile || !filename.trim() || busy || uploadPending) return;
    setUploadPending(true);
    setPanelError('');
    try {
      await onUploadCv(selectedFile, filename);
      setSelectedFile(null);
      setFilename('');
      if (fileInput.current) fileInput.current.value = '';
    } catch (cause) {
      setPanelError(cause instanceof Error ? cause.message : 'Could not upload this CV. Rename it or try again.');
    } finally {
      setUploadPending(false);
    }
  };

  return (
    <section className="my-proficiency-panel" aria-labelledby="my-proficiency-title">
      <header className="proficiency-header">
        <div>
          <p className="eyebrow">LEARNER PROFILE</p>
          <h2 id="my-proficiency-title">My proficiency</h2>
          <p className="muted">
            Your self-reported familiarity guides preparation. It is separate from model suggestions and CV evidence.
          </p>
        </div>
      </header>

      <section className="proficiency-section" aria-labelledby="requirement-title">
        <h3 id="requirement-title">Suggested requirements</h3>
        {requirements.length === 0 ? (
          <p className="muted">Requirements from a generated learning assessment will appear here.</p>
        ) : (
          requirements.map((requirement) => {
            const draftId = visibleDrafts.find((draft) => draft.requirementId === requirement.id)?.id;
            const draft = visibleDrafts.find((item) => item.id === draftId);
            if (!draft) return null;
            return (
              <article className="proficiency-card" key={requirement.id} role="group" aria-label={requirement.concept}>
                <div className="proficiency-card-heading">
                  <div>
                    <h4>{requirement.concept}</h4>
                    <p>{requirement.rationale}</p>
                  </div>
                  <span className="proficiency-source">Model suggestion</span>
                </div>
                <small className="muted">Evidence: {requirement.sourceLabel}</small>
                <p className="proficiency-question">Are you already comfortable with {requirement.concept}?</p>
                <ComfortSelect
                  concept={requirement.concept}
                  value={draft.comfort}
                  disabled={busy || saving || savePending}
                  onChange={(comfort) => updateDraft(draft.id, { comfort })}
                />
                <label className="proficiency-field">
                  Notes for {requirement.concept}
                  <textarea
                    aria-label={`Notes for ${requirement.concept}`}
                    value={draft.note}
                    disabled={busy || saving || savePending}
                    onChange={(event) => updateDraft(draft.id, { note: event.target.value })}
                    rows={2}
                  />
                </label>
                <span className="proficiency-self-report">User self-report</span>
              </article>
            );
          })
        )}
      </section>

      <section className="proficiency-section" aria-labelledby="manual-title">
        <h3 id="manual-title">Your skills and concepts</h3>
        <p className="muted">Add or correct entries at any time. You do not need a CV to manage your proficiency.</p>
        <div className="proficiency-add-row">
          <label className="proficiency-field">
            Add a skill or concept
            <input
              value={newConcept}
              disabled={busy || saving || savePending}
              onChange={(event) => setNewConcept(event.target.value)}
            />
          </label>
          <button className="secondary" type="button" onClick={addSkill} disabled={busy || saving || savePending}>
            Add skill
          </button>
        </div>
        {visibleDrafts
          .filter((draft) => draft.kind === 'manual')
          .map((draft) => (
            <article className="proficiency-card" key={draft.id} role="group" aria-label={draft.concept}>
              <div className="proficiency-card-heading">
                <label className="proficiency-field">
                  Skill or concept
                  <input
                    aria-label={`Skill or concept ${draft.concept}`}
                    value={draft.concept}
                    disabled={busy || saving || savePending}
                    onChange={(event) => updateDraft(draft.id, { concept: event.target.value })}
                  />
                </label>
                <span className="proficiency-self-report">User self-report</span>
              </div>
              <ComfortSelect
                concept={draft.concept}
                value={draft.comfort}
                disabled={busy || saving || savePending}
                onChange={(comfort) => updateDraft(draft.id, { comfort })}
              />
              <label className="proficiency-field">
                Notes for {draft.concept}
                <textarea
                  aria-label={`Notes for ${draft.concept}`}
                  value={draft.note}
                  disabled={busy || saving || savePending}
                  onChange={(event) => updateDraft(draft.id, { note: event.target.value })}
                  rows={2}
                />
              </label>
            </article>
          ))}
        <button className="primary" type="button" disabled={busy || saving || savePending} onClick={submitProficiency}>
          {saving || savePending ? 'Saving…' : 'Save proficiency'}
        </button>
        {notice && (
          <p className="success" role="status">
            {notice}
          </p>
        )}
      </section>

      <section className="proficiency-section" aria-labelledby="cv-title">
        <h3 id="cv-title">Shared CV</h3>
        <p className="muted">
          Your CV is stored outside topics so it can be reused. The original file is retained under its chosen filename.
        </p>
        <div className="proficiency-cv-upload">
          <label className="proficiency-field">
            Upload your CV
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf,.pdf"
              disabled={busy || uploadPending}
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                setSelectedFile(file);
                setFilename(file?.name ?? '');
                setPanelError('');
              }}
            />
          </label>
          <label className="proficiency-field">
            CV filename
            <input
              value={filename}
              disabled={busy || uploadPending || !selectedFile}
              onChange={(event) => setFilename(event.target.value)}
            />
          </label>
          <button className="secondary" type="button" disabled={!canUpload} onClick={submitCv}>
            {uploadPending ? 'Uploading…' : 'Upload CV'}
          </button>
        </div>
        {cvs.length === 0 ? (
          <p className="muted">No CV has been added yet.</p>
        ) : (
          <ul className="proficiency-cv-list">
            {cvs.map((cv) => (
              <li key={cv.id} className={cv.id === selectedCvId ? 'selected' : ''}>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => onSelectCv(cv.id)}
                  disabled={busy || cv.status === 'revoked'}
                >
                  {cv.originalName}
                </button>
                <span className="muted">{cv.status}</span>
                {cv.status !== 'revoked' && (
                  <button type="button" className="text-button" onClick={() => onRevokeCv(cv.id)} disabled={busy}>
                    Stop future use
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {selectedCv && selectedCv.status === 'ready' && (
          <div className="proficiency-cv-preview">
            <h4>Complete extracted text preview</h4>
            <pre>{selectedCv.extractedText}</pre>
            {selectedCv.extractionDiagnostics.length > 0 && (
              <div className="proficiency-warning">
                <strong>Extraction notes</strong>
                <ul>
                  {selectedCv.extractionDiagnostics.map((diagnostic) => (
                    <li key={diagnostic}>{diagnostic}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        <label className="proficiency-cv-toggle">
          <input
            type="checkbox"
            aria-label="Always include CV in this conversation"
            checked={includeCv}
            disabled={busy || (!includeCv && !canIncludeCv)}
            onChange={(event) => onIncludeCvChange(event.target.checked)}
          />
          Always include CV in this conversation
        </label>
        <p className="muted">Complete extracted text is included on every applicable turn and uses more context.</p>
      </section>

      {(panelError || error) && (
        <div role="alert" className="proficiency-error">
          {panelError || error}
        </div>
      )}
    </section>
  );
}
