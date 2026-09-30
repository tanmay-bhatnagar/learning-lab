import { useCallback, useRef, useState } from 'react';
import { stream, topicChatPath } from '../api';
import type { Context, Message, Model, Settings } from '../api/types';
import { chatRequest } from '../modelControls';
import { aborted, errorText } from '../lib/errors';
import { applyStreamEvent, failTurn, startTurn } from '../state/chatStream';

export function useChat(
  topic: string,
  settings: Settings,
  models: Model[],
  thinking: Record<string, boolean | string>,
  selected: string[],
  setError: (message: string) => void,
) {
  const [sending, setSending] = useState(false);
  const streamController = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    streamController.current?.abort();
  }, []);

  const send = useCallback(
    async (
      input: string,
      messages: Message[],
      setMessages: (value: Message[] | ((previous: Message[]) => Message[])) => void,
      setContext: (value: Context) => void,
      onSent: () => void,
    ) => {
      const activeModel = models.find((model) => model.id === settings.model);
      if (!input.trim() || !topic || !activeModel || streamController.current) return;
      const message = input.trim();
      const controller = new AbortController();
      streamController.current = controller;
      setSending(true);
      setError('');
      onSent();
      setMessages((previous) => startTurn(previous, message));
      try {
        await stream(
          topicChatPath(topic),
          chatRequest(settings, activeModel, thinking, message, selected),
          controller.signal,
          (event) => {
            if (event.type === 'done') setContext(event.context || {});
            setMessages((previous) => applyStreamEvent(previous, event));
          },
        );
      } catch (e) {
        const stopRequested = aborted(e);
        setError(
          stopRequested
            ? 'Response stopped. Partial text is shown below; reload history to confirm what was saved.'
            : errorText(e),
        );
        setMessages((previous) => failTurn(previous, stopRequested).messages);
      } finally {
        setSending(false);
        streamController.current = null;
      }
    },
    [topic, settings, models, thinking, selected, setError],
  );

  return { sending, send, stop, streamActive: () => !!streamController.current };
}
