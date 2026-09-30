import type { Message, StreamEvent } from '../api/types';

export function startTurn(messages: Message[], text: string): Message[] {
  return [...messages, { role: 'user', content: text }, { role: 'assistant', content: '', thinking: '' }];
}

export function applyStreamEvent(messages: Message[], event: StreamEvent): Message[] {
  if (!messages.length) return messages;
  const lastIndex = messages.length - 1;
  let next = messages;
  if (event.model) {
    next = next.map((message, index) => (index === lastIndex ? { ...message, model: event.model } : message));
  }
  if (event.type === 'done' && event.retrieval) {
    next = next.map((message, index) => (index === lastIndex ? { ...message, retrieval: event.retrieval } : message));
  }
  if (event.type === 'thinking' || event.type === 'token') {
    next = next.map((message, index) => {
      if (index !== lastIndex) return message;
      if (event.type === 'thinking') {
        return { ...message, thinking: (message.thinking || '') + (event.text || '') };
      }
      return { ...message, content: message.content + (event.text || '') };
    });
  }
  return next;
}

export function failTurn(messages: Message[], stopped: boolean): { messages: Message[]; error?: string } {
  if (!messages.length) return { messages };
  const lastIndex = messages.length - 1;
  return {
    messages: messages.map((message, index) => (index === lastIndex ? { ...message, incomplete: true } : message)),
    error: stopped
      ? 'Response stopped. Partial text is shown below; reload history to confirm what was saved.'
      : undefined,
  };
}
