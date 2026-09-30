import { useEffect, useRef, useState } from 'react';
import type { LabFile, Model } from '../api/types';
import { thinkingValue } from '../modelControls';
import { canSaveLearningGoal } from '../learningGoal';
import { deriveActivity, uploadBlockedReason } from '../state/activity';
import { errorText } from '../lib/errors';
import { useBootstrap } from './useBootstrap';
import { useChat } from './useChat';
import { useFilePreview } from './useFilePreview';
import { useSettings } from './useSettings';
import { useThinkingPrefs } from './useThinkingPrefs';
import { useTopicSession } from './useTopicSession';
import { useUploads } from './useUploads';
import { useSidebarDefault, useTopicSidebarClose, useWindowDragGuards } from './useWindowEffects';

export function useAppState() {
  const [page, setPage] = useState<'workspace' | 'settings'>('workspace');
  const [tab, setTab] = useState<'chat' | 'files' | 'trace'>('chat');
  const [revision, setRevision] = useState(0);
  const [newTopic, setNewTopic] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [goalSaving, setGoalSaving] = useState(false);
  const [preview, setPreview] = useState<LabFile | null>(null);
  const [previewTab, setPreviewTab] = useState<'markdown' | 'original'>('markdown');
  const [follow, setFollow] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);

  const bootstrap = useBootstrap();
  const topicRef = useRef(bootstrap.topic);
  useEffect(() => {
    topicRef.current = bootstrap.topic;
  }, [bootstrap.topic]);

  const session = useTopicSession(bootstrap.topic, revision, bootstrap.setError);
  const { thinking, setThink, storageError } = useThinkingPrefs();
  const activeModel = bootstrap.models.find((m) => m.id === bootstrap.settings.model);
  const chat = useChat(
    bootstrap.topic,
    bootstrap.settings,
    bootstrap.models,
    thinking,
    session.selected,
    bootstrap.setError,
  );
  const uploads = useUploads(bootstrap.topic, topicRef);
  const settingsUi = useSettings(
    bootstrap.settings,
    bootstrap.setSettings,
    bootstrap.setParser,
    bootstrap.models,
    session.setContext,
    bootstrap.setError,
    chat.streamActive,
    () => uploads.uploadLock.current,
    () => chat.sending || uploads.uploading || goalSaving,
  );

  const previewState = useFilePreview(bootstrap.topic, preview, previewTab);
  const { sidebar, setSidebar } = useSidebarDefault();
  useWindowDragGuards(uploads.setDragging, uploads.dragDepthRef);
  const closeSidebarOnMobile = useTopicSidebarClose(setSidebar);

  useEffect(() => {
    settingsUi.syncDraft(bootstrap.settings);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync when server settings change, not when draft edits
  }, [bootstrap.settings]);

  useEffect(() => {
    if (follow) bottom.current?.scrollIntoView({ behavior: chat.sending ? 'instant' : 'smooth', block: 'end' });
  }, [session.messages, chat.sending, follow]);

  useEffect(
    () => () => {
      chat.stop();
      uploads.dispose();
    },
    // chat/uploads objects change each render; stop and dispose are stable
    // eslint-disable-next-line react-hooks/exhaustive-deps -- unmount cleanup only
    [chat.stop, uploads.dispose],
  );

  const activity = deriveActivity({
    sending: chat.sending,
    uploading: uploads.uploading,
    saving: settingsUi.saving,
    goalSaving,
    creating,
    streamLocked: chat.streamActive(),
    uploadLocked: uploads.uploadLock.current,
    persistenceLocked: settingsUi.persistenceLock.current,
  });
  const busy = chat.sending || uploads.uploading || settingsUi.saving || goalSaving;
  const activeTopic = bootstrap.topics.find((t) => t.id === bootstrap.topic);
  const draftModel = bootstrap.models.find((m) => m.id === (settingsUi.switching || settingsUi.draft.model));
  const uploadBlocked = uploadBlockedReason(activity, { topicReady: session.topicReady, hasTopic: !!bootstrap.topic });
  const goalSavable = canSaveLearningGoal({
    hasTopic: !!bootstrap.topic,
    topicReady: session.topicReady,
    busy,
    draft: session.goalDraft,
    saved: session.learningGoal,
  });

  const thinkValue = (model: Model | undefined = activeModel) => thinkingValue(model, thinking);

  const createTopic = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newTopic?.trim()) return;
    setCreating(true);
    bootstrap.setError('');
    try {
      const created = await session.createTopic(newTopic.trim());
      bootstrap.setTopics((previous) => [...previous, created]);
      setPreview(null);
      bootstrap.setTopic(created.id);
      setNewTopic(null);
      setPage('workspace');
    } catch (e) {
      bootstrap.setError(errorText(e));
    } finally {
      setCreating(false);
    }
  };

  const saveLearningGoal = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!goalSavable) return;
    setGoalSaving(true);
    try {
      await session.saveLearningGoal(session.goalDraft);
    } catch (e) {
      bootstrap.setError(errorText(e));
    } finally {
      setGoalSaving(false);
    }
  };

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    if (
      !session.input.trim() ||
      !activeModel ||
      busy ||
      chat.streamActive() ||
      settingsUi.persistenceLock.current ||
      uploads.uploadLock.current ||
      !session.topicReady
    )
      return;
    await chat.send(session.input, session.messages, session.setMessages, session.setContext, () =>
      session.setInput(''),
    );
    setFollow(true);
  };

  const upload = (list: FileList | File[] | null) =>
    void uploads.upload(list, bootstrap.parser, uploadBlocked, bootstrap.setError, (file) =>
      session.setFiles((previous) => [...previous.filter((entry) => entry.id !== file.id), file]),
    );

  const selectTopic = (id: string) => {
    setPreview(null);
    bootstrap.setTopic(id);
  };

  return {
    page,
    setPage,
    tab,
    setTab,
    sidebar,
    setSidebar,
    closeSidebarOnMobile,
    revision,
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
    bootstrap,
    session,
    chat,
    uploads,
    settingsUi,
    previewState,
    storageError,
    busy,
    activeTopic,
    activeModel,
    draftModel,
    uploadBlocked,
    goalSavable,
    goalSaving,
    thinkValue,
    setThink: (value: boolean | string, modelId = bootstrap.settings.model) => setThink(value, modelId),
    createTopic,
    saveLearningGoal,
    send,
    upload,
    refreshFiles: session.refreshFiles,
    selectTopic,
  };
}
