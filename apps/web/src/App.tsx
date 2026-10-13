import { BookOpen, LoaderCircle, Plus, Upload } from 'lucide-react';
import { contextMeter } from './domain/contextMeter';
import { RetrievalTracePanel } from './retrievalTrace';
import { useAppState } from './hooks/useAppState';
import { ChatPanel } from './components/ChatPanel';
import { ConversationBar } from './components/ConversationBar';
import { ErrorBanner } from './components/ErrorBanner';
import { FilesPanel } from './components/FilesPanel';
import { NewTopicModal } from './components/NewTopicModal';
import { PreviewModal } from './components/PreviewModal';
import { SettingsPage } from './components/SettingsPage';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { WorkspaceTabs } from './components/WorkspaceTabs';
import { DocumentMapPanel } from './components/DocumentMapPanel';
import { MyProficiencyPanel } from './components/MyProficiencyPanel';
import { PrerequisitePanel } from './components/PrerequisitePanel';
import { findMapSection } from './state/documentMap';

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
    creating,
    preview,
    setPreview,
    previewTab,
    setPreviewTab,
    follow,
    setFollow,
    bottom,
    selectTopic,
    selectConversation,
    createConversation,
    reloadTopic,
    bootstrap: {
      topics,
      topic,
      models,
      settings,
      settingsReady,
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
    proficiency,
    learnerContext,
    proficiencyEntries,
    proficiencyCvs,
    focusedAssessment,
    prerequisiteImport,
    runProfileActivity,
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
  const documentMap = state.documentMap;
  const sectionSummary = state.sectionSummary;
  const prerequisites = state.prerequisites;
  const currentMap = documentMap.state.response?.map ?? null;
  const selectedMapSection =
    currentMap && sectionSummary.sectionId ? findMapSection(currentMap.sections, sectionSummary.sectionId) : null;
  const focused = learnerContext.preference?.active_assessment ?? null;
  const focusedImport = focused
    ? [...messages].reverse().find((message) => {
        const metadata = message.prerequisite_import;
        return (
          metadata?.topic_id === topic &&
          metadata.conversation_id === session.conversation &&
          metadata.file_id === focused.file_id &&
          metadata.assessment_id === focused.assessment_id &&
          metadata.map_revision === focused.map_revision &&
          metadata.section_id === focused.section_id
        );
      })?.prerequisite_import
    : null;
  const focusedFileName = files.find((file) => file.id === focusedAssessment.assessment?.file_id)?.name ?? '';
  const focusedSectionTitle =
    focusedImport?.section_title ||
    (focused ? 'Saved section assessment' : selectedMapSection?.title || 'Saved section assessment');
  const conversationTitle = session.conversations.find((item) => item.id === session.conversation)?.title ?? 'Default';

  const meter = contextMeter(context, settings);
  const bannerMessage = [error, migrationError, storageError].filter(Boolean).join(' ');
  const uploading = state.activity === 'uploading';
  const saving = state.activity === 'savingSettings';
  const goalSaving = state.activity === 'savingGoal';

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
        onProficiency={() => {
          setPage('proficiency');
          closeSidebarOnMobile();
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
          pageTitle={
            page === 'settings'
              ? 'Settings'
              : page === 'proficiency'
                ? 'My proficiency'
                : activeTopic?.name || 'Welcome'
          }
          onToggleSidebar={() => setSidebar(!sidebar)}
        />
        <ErrorBanner
          message={bannerMessage}
          busy={busy}
          loading={loading}
          onReload={() => {
            if (migrationError || storageError || !topic) void initialize();
            if (topic) reloadTopic();
          }}
          onDismiss={error ? () => setError('') : undefined}
        />
        {loading ? (
          <div className="center-state">
            <LoaderCircle className="spin" />
            <p>Connecting to your workspace…</p>
          </div>
        ) : page === 'proficiency' ? (
          <MyProficiencyPanel
            requirements={[]}
            focusedAssessment={focusedAssessment.assessment}
            focusedAssessmentLoading={focusedAssessment.loading}
            focusedAssessmentError={focusedAssessment.error}
            focusedSectionTitle={focusedSectionTitle}
            focusedFileName={focusedFileName}
            entries={proficiencyEntries}
            cvs={proficiencyCvs}
            selectedCvId={proficiency.profile?.active_cv_id ?? ''}
            activeConversationId={topicReady && !session.conversationPending ? session.conversation : ''}
            conversationTitle={
              session.conversations.find((item) => item.id === session.conversation)?.title ?? 'Default'
            }
            includeCv={learnerContext.preference?.include_cv ?? false}
            preferencesAvailable={!!learnerContext.preference && !learnerContext.error}
            preferenceLoading={learnerContext.loading}
            preferenceError={learnerContext.error}
            onRetryPreferences={learnerContext.reload}
            busy={busy}
            saving={state.activity === 'savingProficiency'}
            refreshing={state.activity === 'refreshingProficiency'}
            proficiencyError={proficiency.proficiencyError ?? ''}
            error={[proficiency.profileError, proficiency.proficiencyError, proficiency.cvError]
              .map((message) =>
                message && proficiencyCvs.some((cv) => cv.extractionDiagnostics.some((item) => message.includes(item)))
                  ? null
                  : message,
              )
              .filter(Boolean)
              .join(' ')}
            notice=""
            onSave={(drafts) => runProfileActivity('saveProficiency', () => proficiency.saveProficiency(drafts))}
            onRefresh={() => runProfileActivity('refreshProficiency', () => proficiency.refreshProficiency())}
            onUploadCv={(file, filename) => runProfileActivity('manageCv', () => proficiency.uploadCv(file, filename))}
            onSelectCv={(id) => {
              void runProfileActivity('manageCv', () => proficiency.selectCv(id)).catch(() => undefined);
            }}
            onRevokeCv={(id) => {
              void runProfileActivity('manageCv', () => proficiency.revokeCv(id)).catch(() => undefined);
            }}
            onIncludeCvChange={(include) => void learnerContext.setIncludeCv(include)}
          />
        ) : page === 'settings' ? (
          <SettingsPage
            draft={draft}
            settings={settings}
            models={models}
            draftModel={draftModel}
            busy={busy}
            settingsReady={settingsReady}
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
            {topic && (
              <ConversationBar
                key={`${topic}:${session.conversation}`}
                conversations={session.conversations}
                activeId={session.conversation}
                disabled={session.conversationPending || !topicReady}
                onSelect={selectConversation}
                onCreate={(title) => void createConversation(title)}
                onRename={(id, title) => void session.renameConversation(id, title)}
              />
            )}
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
            ) : tab === 'map' ? (
              <>
                <DocumentMapPanel
                  topic={topic}
                  files={files}
                  fileId={documentMap.fileId}
                  onFileChange={documentMap.setFileId}
                  map={documentMap.state.response?.map ?? null}
                  status={documentMap.state.response?.status ?? null}
                  loading={documentMap.state.loading}
                  busy={busy}
                  error={documentMap.state.error}
                  conversationTitle={
                    session.conversations.find((item) => item.id === session.conversation)?.title ?? 'Default'
                  }
                  selectedSectionId={sectionSummary.sectionId}
                  summaryView={sectionSummary.view}
                  summaryRunning={sectionSummary.running}
                  summaryImporting={sectionSummary.importing}
                  summaryNotice={sectionSummary.notice}
                  onSelectSection={sectionSummary.selectSection}
                  onGenerateSummary={() => void sectionSummary.generate()}
                  onStopSummary={() => void sectionSummary.stop()}
                  onAddSummary={() => void sectionSummary.addToConversation()}
                  onBuild={() => void documentMap.build()}
                  onRetry={documentMap.reload}
                />
                <PrerequisitePanel
                  key={`${topic}:${documentMap.fileId}:${currentMap?.revision ?? ''}:${sectionSummary.sectionId}`}
                  topicId={topic}
                  fileId={documentMap.fileId}
                  sectionId={sectionSummary.sectionId}
                  sectionTitle={selectedMapSection?.title ?? ''}
                  pageCount={files.find((file) => file.id === documentMap.fileId)?.page_count}
                  fileName={files.find((file) => file.id === documentMap.fileId)?.name ?? documentMap.fileId}
                  units={currentMap?.units ?? []}
                  proficiencyEntries={proficiencyEntries}
                  proficiencyError={proficiency.proficiencyError ?? ''}
                  proficiencySaving={state.activity === 'savingProficiency'}
                  assessment={prerequisites.assessment}
                  assessmentStaleReason={prerequisites.assessmentStaleReason}
                  attempt={prerequisites.attempt}
                  loading={prerequisites.loading}
                  running={prerequisites.running}
                  progress={prerequisites.progress}
                  error={prerequisites.error}
                  blockedReason={prerequisites.blockedReason}
                  modelName={activeModel?.display_name ?? ''}
                  busy={busy}
                  defaultGoal={session.learningGoal}
                  onGenerate={(goal) => void prerequisites.generate(goal)}
                  onStop={() => void prerequisites.stop()}
                  onReload={prerequisites.reload}
                  onOpenMyProficiency={() => setPage('proficiency')}
                  onSaveProficiency={(drafts) =>
                    runProfileActivity('saveProficiency', () => proficiency.saveProficiency(drafts))
                  }
                  onReloadProficiency={() =>
                    runProfileActivity('refreshProficiency', () => proficiency.refreshProficiency())
                  }
                  mainChatTitle={conversationTitle}
                  canImportAssessment={
                    !!session.conversation &&
                    topicReady &&
                    !!learnerContext.preference &&
                    !learnerContext.loading &&
                    !learnerContext.error
                  }
                  canDraftFollowUp={!!session.conversation && topicReady}
                  importing={prerequisiteImport.importing}
                  importNotice={prerequisiteImport.notice}
                  importError={prerequisiteImport.error}
                  preferenceLoading={learnerContext.loading}
                  preferenceError={learnerContext.error}
                  onReloadPreference={learnerContext.reload}
                  onAddToMainChat={prerequisiteImport.addToMainChat}
                  onDraftFollowUp={() => {
                    const fileName = files.find((file) => file.id === documentMap.fileId)?.name ?? documentMap.fileId;
                    const sectionName = selectedMapSection?.title ?? 'this section';
                    const followUp = `I want to understand the concepts needed for “${sectionName}” in ${fileName}. Can you help me explore them using the documents I have selected?`;
                    session.setInput(session.input ? `${session.input}\n\n${followUp}` : followUp);
                    setTab('chat');
                  }}
                />
              </>
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
