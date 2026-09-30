import { useCallback, useEffect, useState } from 'react';
import { api, json, learningGoalPath, topicFilesPath, topicMessagesPath, topicPath } from '../api';
import {
  filesResponseSchema,
  learningGoalResponseSchema,
  messagesResponseSchema,
  topicSchema,
  type Context,
  type LabFile,
  type Message,
} from '../api/types';
import { aborted, errorText } from '../lib/errors';
import { filesRefreshed, goalSaved } from '../state/topicSession';

type SessionSlice = {
  messages: Message[];
  files: LabFile[];
  selected: string[];
  context: Context;
  learningGoal: string;
  goalDraft: string;
  goalNotice: string;
  topicLoading: boolean;
  topicReady: boolean;
  input: string;
};

const emptySession = (): SessionSlice => ({
  messages: [],
  files: [],
  selected: [],
  context: {},
  learningGoal: '',
  goalDraft: '',
  goalNotice: '',
  topicLoading: false,
  topicReady: false,
  input: '',
});

export function useTopicSession(topic: string, revision: number, setError: (message: string) => void) {
  const [session, setSession] = useState<SessionSlice>(emptySession);

  useEffect(() => {
    const controller = new AbortController();
    setSession({ ...emptySession(), topicLoading: !!topic });
    if (!topic) return () => controller.abort();

    Promise.all([
      api(topicMessagesPath(topic), messagesResponseSchema, { signal: controller.signal }),
      api(topicFilesPath(topic), filesResponseSchema, { signal: controller.signal }),
      api(topicPath(topic), topicSchema, { signal: controller.signal }),
    ])
      .then(([history, attachments, topicData]) => {
        const goal = topicData.learning_goal || '';
        setSession({
          messages: history.messages,
          context: history.context || {},
          files: attachments.files,
          selected: [],
          learningGoal: goal,
          goalDraft: goal,
          goalNotice: '',
          topicLoading: false,
          topicReady: true,
          input: '',
        });
      })
      .catch((e) => {
        if (!aborted(e)) setError(errorText(e));
        setSession((previous) => ({ ...previous, topicLoading: false, topicReady: false }));
      });

    return () => controller.abort();
  }, [topic, revision, setError]);

  const refreshFiles = useCallback(async () => {
    if (!topic) return;
    try {
      const attachments = await api(topicFilesPath(topic), filesResponseSchema);
      setSession((previous) => {
        const refreshed = filesRefreshed({ ...previous, preview: null, input: previous.input }, attachments.files);
        return { ...previous, files: refreshed.files, selected: refreshed.selected };
      });
    } catch (e) {
      setError(errorText(e));
    }
  }, [topic, setError]);

  const saveLearningGoal = useCallback(
    async (draft: string) => {
      const saved = await api(
        learningGoalPath(topic),
        learningGoalResponseSchema,
        json({ learning_goal: draft }, 'PUT'),
      );
      setSession((previous) => goalSaved(previous, saved.learning_goal));
    },
    [topic],
  );

  const createTopic = useCallback(async (name: string) => {
    return api('/topics', topicSchema, json({ name }));
  }, []);

  return {
    ...session,
    setSession,
    setMessages: (value: Message[] | ((previous: Message[]) => Message[])) =>
      setSession((previous) => ({
        ...previous,
        messages: typeof value === 'function' ? value(previous.messages) : value,
      })),
    setFiles: (value: LabFile[] | ((previous: LabFile[]) => LabFile[])) =>
      setSession((previous) => ({
        ...previous,
        files: typeof value === 'function' ? value(previous.files) : value,
      })),
    setSelected: (value: string[] | ((previous: string[]) => string[])) =>
      setSession((previous) => ({
        ...previous,
        selected: typeof value === 'function' ? value(previous.selected) : value,
      })),
    setContext: (value: Context) => setSession((previous) => ({ ...previous, context: value })),
    setInput: (value: string) => setSession((previous) => ({ ...previous, input: value })),
    setGoalDraft: (value: string) => setSession((previous) => ({ ...previous, goalDraft: value })),
    refreshFiles,
    saveLearningGoal,
    createTopic,
  };
}
