import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { api, json } from '../api/client';
import { learningGoalPath, topicFilesPath, topicMessagesPath, topicPath } from '../api/urls';
import {
  filesResponseSchema,
  learningGoalResponseSchema,
  messagesResponseSchema,
  topicSchema,
  type LabFile,
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
  const [reloadToken, setReloadToken] = useState(0);
  const topicRef = useRef(topic);
  const refreshController = useRef<AbortController | null>(null);
  const fileRevision = useRef(0);

  useEffect(() => {
    topicRef.current = topic;
  }, [topic]);
  useEffect(
    () => () => {
      refreshController.current?.abort();
      refreshController.current = null;
    },
    [topic],
  );
  if (topic !== trackedTopic) {
    setTrackedTopic(topic);
    dispatch({ type: 'topicRequested' });
  }

  const reload = useCallback(() => {
    fileRevision.current += 1;
    refreshController.current?.abort();
    dispatch({ type: 'topicRequested' });
    setReloadToken((value) => value + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    if (!topic) return () => controller.abort();
    setError('');

    Promise.all([
      api(topicMessagesPath(topic), messagesResponseSchema, { signal: controller.signal }),
      api(topicFilesPath(topic), filesResponseSchema, { signal: controller.signal }),
      api(topicPath(topic), topicSchema, { signal: controller.signal }),
    ])
      .then(([history, attachments, topicData]) => {
        if (controller.signal.aborted || topicRef.current !== topic) return;
        dispatch({
          type: 'topicLoaded',
          payload: {
            messages: history.messages,
            context: history.context || {},
            files: attachments.files,
            topic: topicData,
          },
        });
      })
      .catch((e) => {
        if (aborted(e) || topicRef.current !== topic) return;
        setError(errorText(e));
        dispatch({ type: 'topicFailed' });
      });

    return () => controller.abort();
  }, [topic, reloadToken, setError]);

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
