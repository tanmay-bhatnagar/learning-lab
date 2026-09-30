import React from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  Check,
  ChevronRight,
  FileText,
  FlaskConical,
  LoaderCircle,
  MessageSquare,
  Plus,
  ScanSearch,
  Settings2,
  Square,
  Upload,
  X,
  PanelLeftClose,
  PanelLeftOpen,
  Sparkles,
  ExternalLink,
} from 'lucide-react';
import { fileOriginalPath } from './api';
import { contextMeter } from './domain/contextMeter';
import { fileMeta, isSelectable, showLegacyUnassessedWarning } from './domain/files';
import { APP_CONTEXT_MAX, modelLabel, quantizationLabel } from './modelControls';
import { RetrievalTracePanel } from './retrievalTrace';
import { MessageSources } from './citations';
import { MAX_LEARNING_GOAL_CHARS } from './learningGoal';
import { useAppState } from './hooks/useAppState';
const parserOptions = [
  <option key="docling" value="docling">
    Docling
  </option>,
  <option key="markitdown" value="markitdown">
    MarkItDown (legacy)
  </option>,
  <option key="anydoc" value="anydoc">
    AnyDoc (fallback)
  </option>,
];
function RichText({ text }: { text: string }) {
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          img: ({ alt }) => <span className="muted">[Image: {alt || 'embedded image'}]</span>,
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
export function App() {
  const {
    page,
    setPage,
    tab,
    setTab,
    sidebar,
    setSidebar,
    closeSidebarOnMobile,
    setRevision,
    newTopic,
    setNewTopic,
    creating,
    preview,
    setPreview,
    previewTab,
    setPreviewTab,
    follow,
    setFollow,
    bottom,
    selectTopic,
    bootstrap: {
      topics,
      topic,
      models,
      settings,
      parser,
      setParser,
      loading,
      error,
      setError,
      modelError,
      migrationError,
      initialize,
      refreshModels,
    },
    session: {
      messages,
      files,
      selected,
      setSelected,
      context,
      goalDraft,
      setGoalDraft,
      goalNotice,
      topicLoading,
      topicReady,
      input,
      setInput,
    },
    chat: { sending, stop },
    uploads: {
      uploading,
      dragging,
      setDragging,
      dropBlocked,
      setDropBlocked,
      dropFeedback,
      dragDepthRef,
      uploadInput,
      showDropFeedback,
    },
    settingsUi: {
      draft,
      setDraft,
      saving,
      notice,
      setNotice,
      switching,
      selectionStatus,
      selectionError,
      selectModel,
      saveDraft,
    },
    previewState: { markdown, previewLoading, previewError },
    busy,
    activeTopic,
    activeModel,
    draftModel,
    uploadBlocked,
    goalSavable,
    goalSaving,
    thinkValue,
    setThink,
    createTopic,
    saveLearningGoal,
    send,
    upload,
    refreshFiles,
  } = useAppState();
  const meter = contextMeter(context, settings);
  function thinkingControl(model = activeModel) {
    const kind = model?.thinking?.type;
    if (!kind || kind === 'none') return <span className="muted small">Standard response</span>;
    if (kind === 'always')
      return (
        <span className="thinking-pill">
          <Sparkles size={13} /> Always thinking
        </span>
      );
    if (kind === 'toggle')
      return (
        <label className="thinking-pill">
          <input
            type="checkbox"
            checked={thinkValue(model) === true}
            onChange={(e) => setThink(e.target.checked, model?.id)}
            disabled={busy}
          />
          <Sparkles size={13} /> Thinking {thinkValue(model) === true ? 'On' : 'Off'}
        </label>
      );
    if (kind === 'levels' && model?.thinking.levels?.length)
      return (
        <label className="thinking-pill">
          <Sparkles size={13} />
          <span>Thinking</span>
          <select
            aria-label="Thinking level"
            value={String(thinkValue(model) || '')}
            disabled={busy}
            onChange={(e) => setThink(e.target.value, model.id)}
          >
            {model.thinking.levels.map((level) => (
              <option key={level}>{level}</option>
            ))}
          </select>
        </label>
      );
    return <span className="muted small">Standard response</span>;
  }
  return (
    <div className={`app ${sidebar ? '' : 'collapsed'}`}>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage('workspace');
          }}
        >
          <span className="brand-icon">
            <FlaskConical size={23} />
          </span>
          <span>
            Learning Lab<small>A SPACE FOR CURIOSITY</small>
          </span>
        </a>
        <div className="sidebar-section">
          <span className="eyebrow">YOUR WORKSPACE</span>
          <button className={`nav-item ${page === 'workspace' ? 'active' : ''}`} onClick={() => setPage('workspace')}>
            <MessageSquare size={18} /> Conversations
          </button>
        </div>
        <div className="topic-heading">
          <span className="eyebrow">TOPICS</span>
          <button className="icon-button" aria-label="Create topic" disabled={busy} onClick={() => setNewTopic('')}>
            <Plus size={17} />
          </button>
        </div>
        <div className="topic-list">
          {topics.map((t) => (
            <button
              key={t.id}
              className={`topic-item ${topic === t.id ? 'selected' : ''}`}
              disabled={busy}
              onClick={() => {
                selectTopic(t.id);
                setPage('workspace');
                closeSidebarOnMobile();
              }}
            >
              <BookOpen size={16} />
              <span>{t.name}</span>
              {topic === t.id && <span className="active-dot" />}
            </button>
          ))}
          {!loading && !topics.length && (
            <p className="sidebar-empty">Give your next question a home. Create a topic to begin.</p>
          )}
        </div>
        <button className="new-topic" disabled={busy} onClick={() => setNewTopic('')}>
          <Plus size={17} /> New topic
        </button>
        <div className="sidebar-bottom">
          <div className="local-note">
            <span className="status-dot" />
            <span>
              Local workspace<small>Your topics. Your models.</small>
            </span>
          </div>
          <button
            className={`nav-item ${page === 'settings' ? 'active' : ''}`}
            onClick={() => {
              setDraft(settings);
              setNotice('');
              setPage('settings');
              void refreshModels();
            }}
          >
            <Settings2 size={18} /> Settings
          </button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="icon-button"
              aria-label={sidebar ? 'Hide sidebar' : 'Show sidebar'}
              onClick={() => setSidebar(!sidebar)}
            >
              {sidebar ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
            </button>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{page === 'settings' ? 'Settings' : activeTopic?.name || 'Welcome'}</strong>
          </div>
          <span className="local-badge">LOCAL MODELS</span>
        </header>
        {(error || migrationError) && (
          <div className="banner error" role="alert">
            <span>{error || migrationError}</span>
            <button
              disabled={busy || loading}
              onClick={() => {
                if (topic) setRevision((v) => v + 1);
                else void initialize();
              }}
            >
              Reload
            </button>
            <button className="icon-button" aria-label="Dismiss error" onClick={() => setError('')}>
              <X size={15} />
            </button>
          </div>
        )}
        {loading ? (
          <div className="center-state">
            <LoaderCircle className="spin" />
            <p>Connecting to your workspace…</p>
          </div>
        ) : page === 'settings' ? (
          <div className="settings-scroll">
            <div className="settings-page">
              <span className="eyebrow">MAKE IT YOURS</span>
              <h1>Workspace settings</h1>
              <p className="muted">Choose how your next conversation runs.</p>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void saveDraft();
                }}
              >
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
                      onChange={(e) => selectModel(e.target.value)}
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
                  <button type="button" className="text-button" disabled={busy} onClick={() => void refreshModels()}>
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
                      {thinkingControl(draftModel)}
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
                      onChange={(e) => setDraft({ ...draft, context_limit: Number(e.target.value) })}
                    />
                  </label>
                  <div className="info-note">
                    When the context fills, older input leaves the model’s context automatically. Your saved
                    conversation history stays intact.
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
                      onChange={(e) => setDraft({ ...draft, parser: e.target.value })}
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
                      onChange={(e) => setDraft({ ...draft, embedding_model: e.target.value })}
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
                      onChange={(e) => setDraft({ ...draft, retrieval_top_k: Number(e.target.value) })}
                    />
                  </label>
                </section>
                {notice && (
                  <p role="status" className="success">
                    {notice}
                  </p>
                )}
                <div className="settings-actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      setDraft(settings);
                      setPage('workspace');
                    }}
                  >
                    Back to workspace
                  </button>
                  <button className="primary" disabled={saving || busy || !draft.model}>
                    {saving ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} Save settings
                  </button>
                </div>
              </form>
            </div>
          </div>
        ) : (
          <>
            <div className="workspace-heading">
              <div>
                <span className="eyebrow">LEARN SOMETHING DEEPLY</span>
                <h1>{activeTopic?.name || 'Your next idea starts here'}</h1>
              </div>
              <button
                className="secondary"
                disabled={!topic || busy || !topicReady}
                onClick={() => {
                  setTab('files');
                  uploadInput.current?.click();
                }}
              >
                <Upload size={16} /> Add PDF
              </button>
            </div>
            <div className="tabs">
              <button className={tab === 'chat' ? 'active' : ''} onClick={() => setTab('chat')}>
                <MessageSquare size={16} /> Conversation
              </button>
              <button className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')}>
                <FileText size={16} /> Attached files <span className="count">{files.length}</span>
              </button>
              <button className={tab === 'trace' ? 'active' : ''} onClick={() => setTab('trace')}>
                <ScanSearch size={16} /> Retrieval trace
              </button>
            </div>
            {!topic ? (
              <div className="center-state welcome">
                <span className="hero-icon">
                  <BookOpen size={34} />
                </span>
                <h2>A little structure. A lot to discover.</h2>
                <p>Create a topic, bring your reading, and start a conversation.</p>
                <button className="primary" onClick={() => setNewTopic('')}>
                  <Plus size={16} /> Create your first topic
                </button>
              </div>
            ) : topicLoading ? (
              <div className="center-state">
                <LoaderCircle className="spin" />
                <p>Loading topic…</p>
              </div>
            ) : tab === 'trace' ? (
              <RetrievalTracePanel
                topic={topic}
                files={files}
                selected={selected}
                topK={settings.retrieval_top_k}
                busy={busy}
                topicReady={topicReady}
                onOpenFiles={() => setTab('files')}
              />
            ) : tab === 'files' ? (
              <div
                className={`files-page ${dragging ? 'dragging' : ''} ${dropBlocked ? 'drop-rejected' : ''}`}
                onDragEnter={(e) => {
                  if (!Array.from(e.dataTransfer.types).includes('Files')) return;
                  e.preventDefault();
                  dragDepthRef.current += 1;
                  const blocked = !!uploadBlocked;
                  setDropBlocked(blocked);
                  setDragging(!blocked);
                  if (blocked && uploadBlocked) showDropFeedback(uploadBlocked);
                }}
                onDragOver={(e) => {
                  if (!Array.from(e.dataTransfer.types).includes('Files')) return;
                  e.preventDefault();
                  e.stopPropagation();
                  const blocked = !!uploadBlocked;
                  setDropBlocked(blocked);
                  e.dataTransfer.dropEffect = blocked ? 'none' : 'copy';
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
                  if (!dragDepthRef.current) {
                    setDragging(false);
                    setDropBlocked(false);
                  }
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setDragging(false);
                  dragDepthRef.current = 0;
                  void upload(e.dataTransfer.files);
                }}
              >
                <div className="files-toolbar">
                  <div>
                    <h2>Your reading material</h2>
                    <p className="muted">
                      Drag PDFs into this page or click below to browse. Select documents to include in your next
                      message.
                    </p>
                  </div>
                  <label className="parser-select">
                    PDF parser
                    <select value={parser} disabled={busy} onChange={(e) => setParser(e.target.value)}>
                      {parserOptions}
                    </select>
                  </label>
                </div>
                <button
                  type="button"
                  className={`upload-zone ${dragging ? 'dragging' : ''} ${dropBlocked ? 'drop-rejected' : ''}`}
                  disabled={busy || !topicReady}
                  onClick={() => uploadInput.current?.click()}
                  aria-describedby={dropFeedback ? 'drop-feedback' : undefined}
                >
                  {uploading ? <LoaderCircle className="spin" size={26} /> : <Upload size={26} />}
                  <strong>
                    {uploading
                      ? 'Uploading & parsing your PDF…'
                      : dropBlocked
                        ? 'PDFs only — fix the issue below'
                        : dragging
                          ? 'Release to add your PDFs'
                          : 'Drop PDFs here or click to browse'}
                  </strong>
                  <span>PDF files up to 25 MiB each. Originals stay alongside their parsed Markdown.</span>
                </button>
                {dropFeedback && (
                  <p id="drop-feedback" role="alert" className="drop-feedback">
                    {dropFeedback}
                  </p>
                )}
                <div className="file-list">
                  {files.map((file) => (
                    <div className="file-row" key={file.id}>
                      <input
                        type="checkbox"
                        aria-label={`Include ${file.name} in chat`}
                        checked={selected.includes(file.id)}
                        disabled={busy || !topicReady || !isSelectable(file)}
                        onChange={(e) =>
                          setSelected((previous) =>
                            e.target.checked ? [...previous, file.id] : previous.filter((id) => id !== file.id),
                          )
                        }
                      />
                      <span className="file-icon">
                        <FileText size={23} />
                      </span>
                      <div className="file-details">
                        <strong>{file.name}</strong>
                        <span>{fileMeta(file)}</span>
                        {file.extraction_diagnostics && (
                          <p className={`extraction-diagnostic ${file.extraction_diagnostics.status}`} role="status">
                            <strong>Extraction: {file.extraction_diagnostics.status.replace('_', ' ')}.</strong>{' '}
                            {file.extraction_diagnostics.note}
                            {file.extraction_diagnostics.findings.length > 0 && (
                              <ul>
                                {file.extraction_diagnostics.findings.map((finding, index) => (
                                  <li key={index}>{finding}</li>
                                ))}
                              </ul>
                            )}
                          </p>
                        )}
                        {showLegacyUnassessedWarning(file) && (
                          <p className="field-error" role="status">
                            Extraction fidelity unassessed for this saved record.
                          </p>
                        )}
                        {file.warnings?.map((warning, index) => (
                          <p key={index} className="field-error" role="status">
                            {warning}
                          </p>
                        ))}
                        {file.error && <p className="field-error">{file.error}</p>}
                      </div>
                      <button
                        className="secondary"
                        onClick={() => {
                          setPreview(file);
                          setPreviewTab('markdown');
                        }}
                      >
                        Inspect <ChevronRight size={14} />
                      </button>
                    </div>
                  ))}
                </div>
                {files.length > 0 && (
                  <div className="files-footer">
                    <span>{selected.length} selected for your next message</span>
                    <button className="text-button" onClick={() => setTab('chat')}>
                      Return to conversation →
                    </button>
                    <button className="text-button" disabled={busy} onClick={() => void refreshFiles()}>
                      Refresh files
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <>
                <form className="goal-editor" onSubmit={saveLearningGoal}>
                  <label className="field">
                    Your learning goal for this topic
                    <textarea
                      maxLength={MAX_LEARNING_GOAL_CHARS}
                      rows={2}
                      value={goalDraft}
                      disabled={busy || !topicReady}
                      onChange={(event) => setGoalDraft(event.target.value)}
                      placeholder="What would you like to learn or be able to do?"
                    />
                    <span className="field-hint">
                      This user-authored context is included in chat for this topic. {goalDraft.length}/
                      {MAX_LEARNING_GOAL_CHARS}
                    </span>
                  </label>
                  <button type="submit" className="secondary" disabled={!goalSavable}>
                    {goalSaving ? 'Saving…' : 'Save learning goal'}
                  </button>
                  {goalNotice && (
                    <span className="success" role="status">
                      {goalNotice}
                    </span>
                  )}
                </form>
                <div
                  className="conversation"
                  onScroll={(e) => {
                    const el = e.currentTarget;
                    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 100);
                  }}
                >
                  {!messages.length ? (
                    <div className="chat-empty">
                      <span className="hero-icon">
                        <Sparkles size={30} />
                      </span>
                      <span className="eyebrow">ROOM TO THINK</span>
                      <h2>Follow your curiosity.</h2>
                      <p>
                        Ask a question, explore an idea, or make sense of your reading.
                        <br />
                        Everything here stays with this topic.
                      </p>
                      <div className="starter-grid">
                        {[
                          'Explain a concept step by step',
                          'Help me explore a question',
                          'Find connections in my reading',
                        ].map((label, i) => (
                          <button
                            key={label}
                            onClick={() =>
                              setInput(
                                [
                                  'Explain this concept step by step: ',
                                  'Help me explore this question: ',
                                  'Find connections in the selected reading, focusing on: ',
                                ][i],
                              )
                            }
                          >
                            <BookOpen size={17} />
                            <span>{label}</span>
                            <ChevronRight size={15} />
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="message-list">
                      {messages.map((message, i) => (
                        <article className={`message ${message.role === 'user' ? 'user' : 'assistant'}`} key={i}>
                          <div className="message-avatar">
                            {message.role === 'user' ? 'Y' : <FlaskConical size={17} />}
                          </div>
                          <div className="message-body">
                            <div className="message-author">
                              {message.role === 'user'
                                ? 'You'
                                : message.role === 'assistant'
                                  ? 'Learning Lab'
                                  : message.role}
                              {message.role === 'assistant' && message.model && (
                                <span className="message-model">
                                  {modelLabel(models.find((m) => m.id === message.model) || message.model)}
                                </span>
                              )}
                            </div>
                            {message.thinking && (
                              <details
                                className="thinking-block"
                                open={sending && i === messages.length - 1 && !message.content}
                              >
                                <summary>
                                  <Sparkles size={13} /> Thinking
                                </summary>
                                <RichText text={message.thinking} />
                              </details>
                            )}
                            {message.content && <RichText text={message.content} />}{' '}
                            {!message.content && sending && i === messages.length - 1 && (
                              <div className="generating">
                                <LoaderCircle className="spin" size={14} />{' '}
                                {message.thinking ? 'Reasoning…' : 'Waiting for model…'}
                              </div>
                            )}
                            {message.incomplete && <span className="interrupted">Response incomplete</span>}
                            {message.role === 'assistant' && (
                              <MessageSources topic={topic} files={files} retrieval={message.retrieval} />
                            )}
                          </div>
                        </article>
                      ))}
                      <div ref={bottom} />
                    </div>
                  )}
                </div>
                <div className="composer-area">
                  {!follow && messages.length > 0 && (
                    <button
                      className="latest-button secondary"
                      onClick={() => {
                        setFollow(true);
                        bottom.current?.scrollIntoView({ behavior: 'smooth' });
                      }}
                    >
                      <ArrowDown size={14} /> Latest
                    </button>
                  )}
                  {modelError && (
                    <div className="model-warning">
                      Models: {modelError}{' '}
                      <button className="text-button" disabled={busy} onClick={() => void initialize()}>
                        Retry connection
                      </button>
                    </div>
                  )}
                  {selected.length > 0 && (
                    <button className="attachment-summary" onClick={() => setTab('files')}>
                      <FileText size={14} />
                      {selected.length} {selected.length === 1 ? 'document' : 'documents'} included
                      <ChevronRight size={14} />
                    </button>
                  )}
                  <form className="composer" onSubmit={send}>
                    <textarea
                      aria-label="Message"
                      placeholder={
                        !activeModel
                          ? 'Choose an available model in settings to start…'
                          : 'Ask anything about this topic…'
                      }
                      value={input}
                      disabled={sending || !topicReady}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                          e.preventDefault();
                          e.currentTarget.form?.requestSubmit();
                        }
                      }}
                    />
                    <div className="composer-tools">
                      <div className="composer-options">
                        <button
                          type="button"
                          className="icon-button"
                          aria-label="Select attached files"
                          onClick={() => setTab('files')}
                        >
                          <Plus size={18} />
                        </button>
                        <span className="tool-divider" />
                        <button
                          type="button"
                          className="model-button"
                          aria-label={
                            activeModel ? `Current model: ${modelLabel(activeModel)}` : 'Choose model in settings'
                          }
                          disabled={busy}
                          onClick={() => {
                            setDraft(settings);
                            setPage('settings');
                          }}
                        >
                          {activeModel ? modelLabel(activeModel) : 'Choose model'}
                        </button>
                        {thinkingControl()}
                      </div>
                      {sending ? (
                        <button
                          type="button"
                          className="send-button stop"
                          aria-label="Stop response"
                          onClick={() => stop()}
                        >
                          <Square size={16} />
                        </button>
                      ) : (
                        <button
                          className="send-button"
                          aria-label="Send message"
                          disabled={!input.trim() || !activeModel || busy || !topicReady}
                        >
                          <ArrowUp size={20} />
                        </button>
                      )}
                    </div>
                  </form>
                  <div className="composer-footer">
                    <span>
                      Enter to send <span className="footer-separator">·</span> Shift + Enter for a new line
                    </span>
                    <div
                      className="context"
                      title="Older input drops from model context automatically; saved history remains."
                    >
                      <span className="context-track">
                        <span style={{ width: `${meter.percent}%` }} />
                      </span>
                      <span>
                        {meter.used === undefined
                          ? 'Context'
                          : `${meter.estimated ? '~' : ''}${meter.used.toLocaleString()} /`}{' '}
                        {meter.limit.toLocaleString()}
                        {meter.used === undefined ? ' tokens' : ''}
                      </span>
                    </div>
                  </div>
                </div>
              </>
            )}
          </>
        )}
        <input
          type="file"
          ref={uploadInput}
          accept="application/pdf,.pdf"
          multiple
          hidden
          disabled={busy || !topicReady}
          onChange={(e) => void upload(e.target.files)}
        />
      </main>
      {newTopic !== null && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="topic-title">
            <button
              className="icon-button modal-close"
              aria-label="Close"
              disabled={creating}
              onClick={() => setNewTopic(null)}
            >
              <X size={19} />
            </button>
            <span className="hero-icon">
              <BookOpen size={27} />
            </span>
            <h2 id="topic-title">Make room for a new topic</h2>
            <p className="muted">Keep a conversation and its reading in one place.</p>
            <form onSubmit={createTopic}>
              <label className="field">
                Topic name
                <input
                  autoFocus
                  required
                  maxLength={120}
                  placeholder="e.g. Understanding neural networks"
                  value={newTopic}
                  onChange={(e) => setNewTopic(e.target.value)}
                />
              </label>
              {error && (
                <p role="alert" className="field-error">
                  {error}
                </p>
              )}
              <button className="primary" disabled={creating || !newTopic.trim()}>
                {creating ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />} Create topic
              </button>
            </form>
          </section>
        </div>
      )}
      {preview && (
        <div className="modal-backdrop">
          <section className="preview-modal" role="dialog" aria-modal="true" aria-label={`Inspect ${preview.name}`}>
            <div className="preview-header">
              <FileText size={20} />
              <strong>{preview.name}</strong>
              <button className="icon-button" aria-label="Close preview" onClick={() => setPreview(null)}>
                <X size={20} />
              </button>
            </div>
            <div className="tabs">
              <button className={previewTab === 'markdown' ? 'active' : ''} onClick={() => setPreviewTab('markdown')}>
                Parsed Markdown
              </button>
              <button className={previewTab === 'original' ? 'active' : ''} onClick={() => setPreviewTab('original')}>
                Original PDF
              </button>
              <a
                className="original-link"
                target="_blank"
                rel="noopener noreferrer"
                href={`/api${fileOriginalPath(topic, preview.id)}`}
              >
                Open PDF <ExternalLink size={13} />
              </a>
            </div>
            <div className="preview-content">
              {previewTab === 'original' ? (
                <iframe title={`Original PDF: ${preview.name}`} src={`/api${fileOriginalPath(topic, preview.id)}`} />
              ) : previewLoading ? (
                <div className="center-state">
                  <LoaderCircle className="spin" />
                  Loading Markdown…
                </div>
              ) : previewError ? (
                <p role="alert" className="field-error">
                  {previewError}
                </p>
              ) : markdown ? (
                <RichText text={markdown} />
              ) : (
                <p className="muted">No Markdown content is available yet.</p>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
