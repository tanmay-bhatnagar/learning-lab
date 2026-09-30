import { useEffect, useRef, useState } from 'react';
import { api, json } from '../api/client';
import { topicSchema, type LabFile, type Model } from '../api/types';
import { thinkingValue } from '../modelControls';
import { canSaveLearningGoal } from '../learningGoal';
import { errorText } from '../lib/errors';
import { isBusy } from '../state/activity';
import { useActivity } from './useActivity';
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
  const [newTopic, setNewTopic] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [preview, setPreview] = useState<LabFile | null>(null);
  const [previewTab, setPreviewTab] = useState<'markdown' | 'original'>('markdown');
  const [follow, setFollow] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);

  const activityApi = useActivity();
  const bootstrap = useBootstrap();
  const topicRef = useRef(bootstrap.topic);
  useEffect(() => {
    topicRef.current = bootstrap.topic;
  }, [bootstrap.topic]);

  const session = useTopicSession(bootstrap.topic, bootstrap.setError, activityApi.activity, activityApi);
  const { thinking, setThink, storageError } = useThinkingPrefs();
  const activeModel = bootstrap.models.find((m) => m.id === bootstrap.settings.model);

  const chat = useChat(
    bootstrap.topic,
    bootstrap.settings,
    bootstrap.models,
    thinking,
    session.selected,
    session.topicReady,
    session,
    bootstrap.setError,
    activityApi,
  );

  const uploads = useUploads(bootstrap.topic, topicRef, activityApi.activity, session.topicReady, activityApi);

  const settingsUi = useSettings(
    bootstrap.settings,
    bootstrap.setSettings,
    bootstrap.setParser,
    bootstrap.models,
    (context) => session.dispatch({ type: 'contextChanged', context }),
    bootstrap.setError,
    activityApi.activity,
    activityApi,
  );

  const previewState = useFilePreview(bootstrap.topic, preview, previewTab);
  const { sidebar, setSidebar } = useSidebarDefault();
  useWindowDragGuards(uploads.setDragging, uploads.dragDepthRef);
  const closeSidebarOnMobile = useTopicSidebarClose(setSidebar);

  const sending = activityApi.activity === 'sending';
  const busy = isBusy(activityApi.activity);

  useEffect(() => {
    if (follow) bottom.current?.scrollIntoView({ behavior: sending ? 'instant' : 'smooth', block: 'end' });
  }, [session.messages, sending, follow]);

  useEffect(() => {
    const stop = chat.stop;
    const dispose = uploads.dispose;
    return () => {
      stop();
      dispose();
    };
  }, [chat.stop, uploads.dispose]);

  const activeTopic = bootstrap.topics.find((t) => t.id === bootstrap.topic);
  const draftModel = bootstrap.models.find((m) => m.id === (settingsUi.switching || settingsUi.draft.model));
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
    if (newTopic === null || !newTopic.trim() || creating) return;
    setCreating(true);
    bootstrap.setError('');
    try {
      const created = await api('/topics', topicSchema, json({ name: newTopic.trim() }));
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

  const upload = (list: FileList | File[] | null) =>
    void uploads.upload(list, bootstrap.parser, bootstrap.setError, session.appendFile);

  const selectTopic = (id: string) => {
    setPreview(null);
    bootstrap.setTopic(id);
  };

  const reloadTopic = () => {
    setPreview(null);
    session.reload();
  };

  return {
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
    bootstrap,
    session,
    chat,
    uploads,
    settingsUi,
    previewState,
    storageError,
    activity: activityApi.activity,
    busy,
    sending,
    activeTopic,
    activeModel,
    draftModel,
    uploadBlocked: uploads.uploadBlocked,
    goalSavable,
    thinkValue,
    setThink: (value: boolean | string, modelId = bootstrap.settings.model) => setThink(value, modelId),
    createTopic,
    saveLearningGoal: session.saveLearningGoal,
    send: chat.send,
    stop: chat.stop,
    upload,
    refreshFiles: session.refreshFiles,
    selectTopic,
    reloadTopic,
  };
}
