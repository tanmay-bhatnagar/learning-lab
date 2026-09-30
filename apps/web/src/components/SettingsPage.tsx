import { Check, LoaderCircle, Sparkles } from 'lucide-react';
import type { Model, Settings } from '../api/types';
import { APP_CONTEXT_MAX, modelLabel, quantizationLabel } from '../modelControls';
import { parserOptions } from './parserOptions';
import { ThinkingControl } from './ThinkingControl';

type Props = {
  draft: Settings;
  settings: Settings;
  models: Model[];
  draftModel?: Model;
  busy: boolean;
  saving: boolean;
  switching: string;
  selectionStatus: string;
  selectionError: string;
  modelError: string;
  notice: string;
  thinkValue: (model?: Model) => boolean | string | undefined;
  onDraftChange: (draft: Settings) => void;
  onSelectModel: (modelId: string) => void;
  onRefreshModels: () => void;
  onThinkChange: (value: boolean | string, modelId?: string) => void;
  onSave: (event: React.FormEvent) => void;
  onBack: () => void;
};

export function SettingsPage({
  draft,
  settings,
  models,
  draftModel,
  busy,
  saving,
  switching,
  selectionStatus,
  selectionError,
  modelError,
  notice,
  thinkValue,
  onDraftChange,
  onSelectModel,
  onRefreshModels,
  onThinkChange,
  onSave,
  onBack,
}: Props) {
  return (
    <div className="settings-scroll">
      <div className="settings-page">
        <span className="eyebrow">MAKE IT YOURS</span>
        <h1>Workspace settings</h1>
        <p className="muted">Choose how your next conversation runs.</p>
        <form onSubmit={onSave}>
          <section className="settings-card">
            <div className="section-title">
              <span className="tile">
                <Sparkles size={20} />
              </span>
              <div>
                <h2>Model & reasoning</h2>
                <p>Use a model available on your local server.</p>
              </div>
            </div>
            <label className="field">
              Default model
              <select
                title={
                  switching
                    ? modelLabel(models.find((m) => m.id === switching) || switching)
                    : settings.model
                      ? modelLabel(models.find((m) => m.id === settings.model) || settings.model)
                      : 'Select a model'
                }
                disabled={busy}
                value={switching || settings.model}
                onChange={(e) => onSelectModel(e.target.value)}
              >
                <option value="" disabled>
                  Select a model
                </option>
                {draft.model && !models.some((m) => m.id === draft.model) && (
                  <option value={draft.model}>{modelLabel(draft.model)} (unavailable)</option>
                )}
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {modelLabel(m)}
                  </option>
                ))}
              </select>
            </label>
            <div className="selection-feedback" aria-live="polite">
              {switching ? (
                <p role="status">
                  <LoaderCircle className="spin" size={14} /> Switching to{' '}
                  {modelLabel(models.find((m) => m.id === switching) || switching)}…
                </p>
              ) : selectionStatus ? (
                <p role="status" className="success">
                  {selectionStatus}
                </p>
              ) : (
                <p className="muted small">Model changes apply immediately.</p>
              )}
            </div>
            {selectionError && (
              <p role="alert" className="field-error">
                {selectionError}
              </p>
            )}
            {modelError && <p className="field-error">{modelError}</p>}
            <button type="button" className="text-button" disabled={busy} onClick={onRefreshModels}>
              Refresh available models
            </button>
            {draftModel && (
              <div className="model-details">
                <span
                  className="model-id"
                  tabIndex={0}
                  title={draftModel.id}
                  aria-label={`Technical model id: ${draftModel.id}`}
                >
                  Technical details
                </span>
                <p className="muted">
                  {[
                    quantizationLabel(draftModel.quantization),
                    draftModel.size_bytes ? `${(draftModel.size_bytes / 1e9).toFixed(1)} GB download` : undefined,
                  ]
                    .filter(Boolean)
                    .join(' · ') || 'Size unavailable'}
                  {draftModel.size_bytes ? '; runtime memory is additional.' : ''}
                </p>
                <ThinkingControl model={draftModel} busy={busy} thinkValue={thinkValue} onThinkChange={onThinkChange} />
                {draftModel.thinking.type === 'toggle' && (
                  <p className="muted">This model supports on/off reasoning; effort levels aren't supported.</p>
                )}
                {draftModel.thinking.type === 'levels' && (
                  <p className="muted">Choose a reasoning effort level for this model.</p>
                )}
              </div>
            )}
            <div className="provider-row">
              <span className="provider enabled">
                Local <Check size={13} />
              </span>
              {['OpenAI', 'Grok', 'Anthropic', 'Gemini'].map((name) => (
                <button key={name} type="button" disabled title="Not available yet" className="provider">
                  {name}
                  <small>Coming soon</small>
                </button>
              ))}
            </div>
          </section>
          <section className="settings-card">
            <h2>Conversation context</h2>
            <p className="muted">The token budget available to the model for each response.</p>
            <label className="field">
              Context limit{' '}
              <span className="field-hint">Default & maximum: {APP_CONTEXT_MAX.toLocaleString()} tokens</span>
              <input
                type="number"
                min="1024"
                max={APP_CONTEXT_MAX}
                disabled={busy}
                step="1"
                required
                value={draft.context_limit || ''}
                onChange={(e) => onDraftChange({ ...draft, context_limit: Number(e.target.value) })}
              />
            </label>
            <div className="info-note">
              When the context fills, older input leaves the model’s context automatically. Your saved conversation
              history stays intact.
            </div>
          </section>
          <section className="settings-card">
            <h2>Document parsing</h2>
            <p className="muted">The default converter for new PDF uploads and local retrieval settings.</p>
            <label className="field">
              PDF parser
              <select
                disabled={busy}
                value={draft.parser}
                onChange={(e) => onDraftChange({ ...draft, parser: e.target.value })}
              >
                {parserOptions}
              </select>
            </label>
            <label className="field">
              Embedding model
              <span className="field-hint">Local model id used when hybrid retrieval is available</span>
              <input
                type="text"
                maxLength={200}
                disabled={busy}
                required
                value={draft.embedding_model}
                onChange={(e) => onDraftChange({ ...draft, embedding_model: e.target.value })}
              />
            </label>
            <label className="field">
              Retrieval top-k<span className="field-hint">Chunks included per query (1–20)</span>
              <input
                type="number"
                min="1"
                max="20"
                disabled={busy}
                step="1"
                required
                value={draft.retrieval_top_k || ''}
                onChange={(e) => onDraftChange({ ...draft, retrieval_top_k: Number(e.target.value) })}
              />
            </label>
          </section>
          {notice && (
            <p role="status" className="success">
              {notice}
            </p>
          )}
          <div className="settings-actions">
            <button type="button" className="secondary" onClick={onBack}>
              Back to workspace
            </button>
            <button className="primary" disabled={saving || busy || !draft.model}>
              {saving ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} Save settings
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
