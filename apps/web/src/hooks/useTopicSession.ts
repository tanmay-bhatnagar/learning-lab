import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { api, json } from '../api/client';
import {
  conversationMessagesPath,
  conversationPath,
  conversationsPath,
  learningGoalPath,
  topicFilesPath,
  topicPath,
} from '../api/urls';
import {
  filesResponseSchema,
  conversationSchema,
  conversationsResponseSchema,
  learningGoalResponseSchema,
  messagesResponseSchema,
  topicSchema,
  type LabFile,
  type Conversation,
  selectedFilesSchema,
} from '../api/types';
import { aborted, errorText } from '../lib/errors';
import { canSaveLearningGoal } from '../learningGoal';
import { isBusy, type Activity } from '../state/activity';
import { emptyTopicSession, topicSessionReducer } from '../state/topicSession';
import type { useActivity } from './useActivity';

type ActivityApi = Pick<ReturnType<typeof useActivity>, 'begin' | 'end'>;

export function useTopicSession(
  topic: string,
  setError: (message: string) => void,
  activity: Activity,
  activityApi: ActivityApi,
) {
  const [state, dispatch] = useReducer(topicSessionReducer, emptyTopicSession());
  const [trackedTopic, setTrackedTopic] = useState(topic);
  const [conversation, setConversation] = useState('default');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationPending, setConversationPending] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const topicRef = useRef(topic);
  const conversationMutationRevision = useRef(0);
  const conversationMutationController = useRef<AbortController | null>(null);
  const refreshController = useRef<AbortController | null>(null);
  const fileRevision = useRef(0);

  const selectionKey = `learning-lab:selected:${topic}:${conversation}`;
  useEffect(() => {
    if (!state.topicReady) return;
    try {
      localStorage.setItem(selectionKey, JSON.stringify(state.selected));
    } catch (error) {
      setError(`Could not save selected files: ${errorText(error)}`);
    }
  }, [selectionKey, state.selected, state.topicReady, setError]);

  useEffect(() => {
    topicRef.current = topic;
    return () => {
      conversationMutationRevision.current += 1;
      conversationMutationController.current?.abort();
      conversationMutationController.current = null;
    };
  }, [topic]);
  useEffect(
    () => () => {
      refreshController.current?.abort();
      refreshController.current = null;
    },
    [topic],
  );
  if (topic !== trackedTopic) {
    setConversationPending(false);
    setTrackedTopic(topic);
    setConversation('default');
    setConversations([]);
    dispatch({ type: 'topicRequested' });
  }

  const reload = useCallback(() => {
    fileRevision.current += 1;
    refreshController.current?.abort();
    dispatch({ type: 'conversationRequested' });
    setReloadToken((value) => value + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    if (!topic) return () => controller.abort();
    setError('');

    Promise.all([
      api(conversationMessagesPath(topic, conversation), messagesResponseSchema, { signal: controller.signal }),
      api(topicFilesPath(topic), filesResponseSchema, { signal: controller.signal }),
      api(topicPath(topic), topicSchema, { signal: controller.signal }),
      api(conversationsPath(topic), conversationsResponseSchema, { signal: controller.signal }),
    ])
      .then(([history, attachments, topicData, catalog]) => {
        if (controller.signal.aborted || topicRef.current !== topic) return;
        setConversations(catalog.conversations);
        setConversationPending(false);
        dispatch({
          type: 'topicLoaded',
          payload: {
            messages: history.messages,
            context: history.context || {},
            files: attachments.files,
            selected: (() => {
              try {
                const stored = localStorage.getItem(selectionKey);
                if (!stored) return [];
                const parsed = selectedFilesSchema.parse(JSON.parse(stored));
                const available = new Set(attachments.files.map((file) => file.id));
                return parsed.filter((id) => available.has(id));
              } catch {
                // Invalid or unavailable browser storage must not block loading saved chat history.
                return [];
              }
            })(),
            topic: topicData,
          },
        });
      })
      .catch((e) => {
        if (aborted(e) || topicRef.current !== topic) return;
        setError(errorText(e));
        setConversationPending(false);
        dispatch({ type: 'topicFailed' });
      });

    return () => controller.abort();
  }, [topic, conversation, reloadToken, setError, selectionKey]);

  const selectConversation = useCallback(
    (id: string) => {
      if (id === conversation || !conversations.some((item) => item.id === id)) return;
      setConversationPending(true);
      dispatch({ type: 'conversationRequested' });
      setConversation(id);
    },
    [conversation, conversations],
  );

  const createConversation = useCallback(
    async (title: string) => {
      if (!topic || !title.trim() || conversationPending || conversationMutationController.current) return;
      const revision = ++conversationMutationRevision.current;
      const controller = new AbortController();
      conversationMutationController.current = controller;
      setConversationPending(true);
      try {
        const created = await api(conversationsPath(topic), conversationSchema, {
          ...json({ title: title.trim() }),
          signal: controller.signal,
        });
        if (
          controller.signal.aborted ||
          topicRef.current !== topic ||
          revision !== conversationMutationRevision.current
        )
          return;
        setConversations((previous) => [...previous, created]);
        dispatch({ type: 'conversationRequested' });
        setConversation(created.id);
      } catch (e) {
        if (!aborted(e) && topicRef.current === topic && revision === conversationMutationRevision.current) {
          setError(errorText(e));
        }
      } finally {
        if (revision === conversationMutationRevision.current) {
          conversationMutationController.current = null;
          setConversationPending(false);
        }
      }
    },
    [topic, conversationPending, setError],
  );

  const renameConversation = useCallback(
    async (id: string, title: string) => {
      if (!topic || !title.trim() || conversationPending || conversationMutationController.current) return;
      const revision = ++conversationMutationRevision.current;
      const controller = new AbortController();
      conversationMutationController.current = controller;
      setConversationPending(true);
      try {
        const updated = await api(conversationPath(topic, id), conversationSchema, {
          ...json({ title: title.trim() }, 'PATCH'),
          signal: controller.signal,
        });
        if (
          controller.signal.aborted ||
          topicRef.current !== topic ||
          revision !== conversationMutationRevision.current
        )
          return;
        setConversations((previous) => previous.map((item) => (item.id === id ? updated : item)));
      } catch (e) {
        if (!aborted(e) && topicRef.current === topic && revision === conversationMutationRevision.current) {
          setError(errorText(e));
        }
      } finally {
        if (revision === conversationMutationRevision.current) {
          conversationMutationController.current = null;
          setConversationPending(false);
        }
      }
    },
    [topic, conversationPending, setError],
  );

  const refreshFiles = useCallback(async () => {
    if (!topic || isBusy(activity)) return;
    refreshController.current?.abort();
    const controller = new AbortController();
    refreshController.current = controller;
    const target = topic;
    const revision = fileRevision.current;
    try {
      const attachments = await api(topicFilesPath(target), filesResponseSchema, { signal: controller.signal });
      if (controller.signal.aborted || topicRef.current !== target || revision !== fileRevision.current) return;
      dispatch({ type: 'filesRefreshed', files: attachments.files });
    } catch (e) {
      if (aborted(e) || topicRef.current !== target) return;
      setError(errorText(e));
    } finally {
      if (refreshController.current === controller) refreshController.current = null;
    }
  }, [topic, activity, setError]);

  const saveLearningGoal = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      const savable = canSaveLearningGoal({
        hasTopic: !!topic,
        topicReady: state.topicReady,
        busy: isBusy(activity),
        draft: state.goalDraft,
        saved: state.learningGoal,
      });
      if (!savable || !activityApi.begin('saveGoal')) return;
      const target = topic;
      try {
        const saved = await api(
          learningGoalPath(target),
          learningGoalResponseSchema,
          json({ learning_goal: state.goalDraft }, 'PUT'),
        );
        if (topicRef.current !== target) return;
        dispatch({ type: 'goalSaved', learningGoal: saved.learning_goal });
      } catch (e) {
        if (topicRef.current !== target) return;
        setError(errorText(e));
      } finally {
        activityApi.end();
      }
    },
    [topic, state.topicReady, state.goalDraft, state.learningGoal, activity, activityApi, setError],
  );

  const appendFile = useCallback((file: LabFile) => {
    fileRevision.current += 1;
    refreshController.current?.abort();
    dispatch({ type: 'fileUploaded', file });
  }, []);

  return {
    ...state,
    conversation,
    conversations,
    conversationPending,
    selectConversation,
    createConversation,
    renameConversation,
    dispatch,
    setInput: (value: string) => dispatch({ type: 'inputChanged', value }),
    setGoalDraft: (value: string) => dispatch({ type: 'goalDraftChanged', value }),
    reload,
    refreshFiles,
    saveLearningGoal,
    appendFile,
  };
}

export type TopicSession = ReturnType<typeof useTopicSession>;
