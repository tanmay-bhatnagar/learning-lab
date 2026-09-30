import { BookOpen, LoaderCircle, Plus, Upload } from 'lucide-react';
import { contextMeter } from './domain/contextMeter';
import { RetrievalTracePanel } from './retrievalTrace';
import { useAppState } from './hooks/useAppState';
import { ChatPanel } from './components/ChatPanel';
import { ErrorBanner } from './components/ErrorBanner';
import { FilesPanel } from './components/FilesPanel';
import { NewTopicModal } from './components/NewTopicModal';
import { PreviewModal } from './components/PreviewModal';
import { SettingsPage } from './components/SettingsPage';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { WorkspaceTabs } from './components/WorkspaceTabs';

export function App() {
  const state = useAppState();
  const {
    page,
    setPage,
    tab,
    setTab,
    sidebar,
    setSidebar,
    closeSidebarOnMobile,
    newTopic,
    setNewTopic,
    preview,
    setPreview,
    previewTab,
    setPreviewTab,
    follow,
    setFollow,
    bottom,
    selectTopic,
    reloadTopic,
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
    session,
    uploads: {
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
      notice,
      setNotice,
      switching,
      selectionStatus,
      selectionError,
      selectModel,
      saveDraft,
    },
    previewState: { markdown, previewLoading, previewError },
    storageError,
    activity,
    busy,
    sending,
    activeTopic,
    activeModel,
    draftModel,
    uploadBlocked,
    goalSavable,
    thinkValue,
    setThink,
    createTopic,
    saveLearningGoal,
    send,
    stop,
    upload,
    refreshFiles,
  } = state;

  const {
    messages,
    files,
    selected,
    context,
    goalDraft,
    goalNotice,
    topicLoading,
    topicReady,
    input,
    setInput,
    setGoalDraft,
    dispatch: sessionDispatch,
  } = session;

  const meter = contextMeter(context, settings);
  const bannerMessage = [error, migrationError, storageError].filter(Boolean).join(' ');
  const creating = activity === 'creatingTopic';
  const uploading = activity === 'uploading';
  const saving = activity === 'savingSettings';
  const goalSaving = activity === 'savingGoal';

  return (
    <div className={`app ${sidebar ? '' : 'collapsed'}`}>
      <Sidebar
        page={page}
        topics={topics}
        topic={topic}
        loading={loading}
        busy={busy}
        onWorkspace={() => setPage('workspace')}
        onSettings={() => {
          setDraft(settings);
          setNotice('');
          setPage('settings');
          void refreshModels();
        }}
        onNewTopic={() => setNewTopic('')}
        onSelectTopic={(id) => {
          selectTopic(id);
          setPage('workspace');
          closeSidebarOnMobile();
        }}
      />
      <main>
        <TopBar
          sidebar={sidebar}
          pageTitle={page === 'settings' ? 'Settings' : activeTopic?.name || 'Welcome'}
          onToggleSidebar={() => setSidebar(!sidebar)}
        />
        <ErrorBanner
          message={bannerMessage}
          busy={busy}
          loading={loading}
          onReload={() => {
            if (topic) reloadTopic();
            else void initialize();
          }}
          onDismiss={() => setError('')}
        />
        {loading ? (
          <div className="center-state">
            <LoaderCircle className="spin" />
            <p>Connecting to your workspace…</p>
          </div>
        ) : page === 'settings' ? (
          <SettingsPage
            draft={draft}
            settings={settings}
            models={models}
            draftModel={draftModel}
            busy={busy}
            saving={saving}
            switching={switching}
            selectionStatus={selectionStatus}
            selectionError={selectionError}
            modelError={modelError}
            notice={notice}
            thinkValue={thinkValue}
            onDraftChange={setDraft}
            onSelectModel={selectModel}
            onRefreshModels={() => void refreshModels()}
            onThinkChange={setThink}
            onSave={(event) => void saveDraft(event)}
            onBack={() => {
              setDraft(settings);
              setPage('workspace');
            }}
          />
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
            <WorkspaceTabs tab={tab} fileCount={files.length} onTab={setTab} />
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
              <FilesPanel
                files={files}
                selected={selected}
                parser={parser}
                busy={busy}
                topicReady={topicReady}
                uploading={uploading}
                dragging={dragging}
                dropBlocked={dropBlocked}
                dropFeedback={dropFeedback}
                uploadBlocked={uploadBlocked}
                dragDepthRef={dragDepthRef}
                onParserChange={setParser}
                onToggleFile={(fileId, checked) => sessionDispatch({ type: 'selectionToggled', fileId, checked })}
                onInspect={(file) => {
                  setPreview(file);
                  setPreviewTab('markdown');
                }}
                onUploadClick={() => uploadInput.current?.click()}
                onDrop={(list) => void upload(list)}
                setDragging={setDragging}
                setDropBlocked={setDropBlocked}
                showDropFeedback={showDropFeedback}
                onReturnToChat={() => setTab('chat')}
                onRefreshFiles={() => void refreshFiles()}
              />
            ) : (
              <ChatPanel
                messages={messages}
                models={models}
                topic={topic}
                files={files}
                goalDraft={goalDraft}
                goalSavable={goalSavable}
                goalSaving={goalSaving}
                goalNotice={goalNotice}
                input={input}
                sending={sending}
                busy={busy}
                topicReady={topicReady}
                follow={follow}
                selectedCount={selected.length}
                activeModel={activeModel}
                modelError={modelError}
                meter={meter}
                bottomRef={bottom}
                thinkValue={thinkValue}
                onGoalChange={setGoalDraft}
                onGoalSubmit={saveLearningGoal}
                onInputChange={setInput}
                onSend={send}
                onStop={stop}
                onScroll={(e) => {
                  const el = e.currentTarget;
                  setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 100);
                }}
                onFollowLatest={() => setFollow(true)}
                onOpenFiles={() => setTab('files')}
                onOpenSettings={() => {
                  setDraft(settings);
                  setPage('settings');
                }}
                onThinkChange={setThink}
                onRetryConnection={() => void initialize()}
                onStarterPrompt={setInput}
              />
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
        <NewTopicModal
          name={newTopic}
          creating={creating}
          error={error}
          onChange={setNewTopic}
          onClose={() => setNewTopic(null)}
          onSubmit={createTopic}
        />
      )}
      {preview && (
        <PreviewModal
          topic={topic}
          file={preview}
          tab={previewTab}
          markdown={markdown}
          loading={previewLoading}
          error={previewError}
          onTab={setPreviewTab}
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  );
}
