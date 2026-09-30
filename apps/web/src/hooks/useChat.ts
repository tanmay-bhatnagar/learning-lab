import { useCallback, useEffect, useRef } from 'react';
import { stream } from '../api/client';
import { topicChatPath } from '../api/urls';
import type { Model, Settings } from '../api/types';
import { chatRequest } from '../modelControls';
import { aborted, errorText } from '../lib/errors';
import { applyStreamEvent, failTurn, startTurn } from '../state/chatStream';
import type { TopicSession } from './useTopicSession';
import type { useActivity } from './useActivity';

type ActivityApi = Pick<ReturnType<typeof useActivity>, 'begin' | 'end'>;

export function useChat(
  topic: string,
  settings: Settings,
  models: Model[],
  thinking: Record<string, boolean | string>,
  selected: string[],
  topicReady: boolean,
  session: TopicSession,
  setError: (message: string) => void,
  activityApi: ActivityApi,
) {
  const streamController = useRef<AbortController | null>(null);
  const topicRef = useRef(topic);

  useEffect(() => {
    topicRef.current = topic;
  }, [topic]);

  const stop = useCallback(() => {
    streamController.current?.abort();
  }, []);

  const send = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      const activeModel = models.find((model) => model.id === settings.model);
      const input = session.input.trim();
      if (!input || !topic || !activeModel || !topicReady || !activityApi.begin('send')) return;

      const message = input;
      const controller = new AbortController();
      streamController.current = controller;
      const target = topic;
      setError('');
      session.dispatch({ type: 'inputChanged', value: '' });
      session.dispatch({ type: 'messagesChanged', value: (previous) => startTurn(previous, message) });

      try {
        await stream(
          topicChatPath(target),
          chatRequest(settings, activeModel, thinking, message, selected),
          controller.signal,
          (event) => {
            if (topicRef.current !== target) return;
            if (event.type === 'done') session.dispatch({ type: 'contextChanged', context: event.context || {} });
            session.dispatch({
              type: 'messagesChanged',
              value: (previous) => applyStreamEvent(previous, event),
            });
          },
        );
      } catch (e) {
        if (topicRef.current !== target) return;
        const stopRequested = aborted(e);
        setError(
          stopRequested
            ? 'Response stopped. Partial text is shown below; reload history to confirm what was saved.'
            : errorText(e),
        );
        session.dispatch({
          type: 'messagesChanged',
          value: (previous) => failTurn(previous, stopRequested).messages,
        });
      } finally {
        streamController.current = null;
        activityApi.end();
      }
    },
    [topic, settings, models, thinking, selected, topicReady, session, setError, activityApi],
  );

  return { send, stop };
}
