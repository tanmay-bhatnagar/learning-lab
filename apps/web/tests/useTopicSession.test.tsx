import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { useActivity } from '../src/hooks/useActivity';
import { useTopicSession } from '../src/hooks/useTopicSession';
import { installFakeApi } from './fakeApi';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  localStorage.clear();
});

test('a stale rename response cannot clear the current topic mutation state', async () => {
  installFakeApi();
  const originalFetch = globalThis.fetch;
  const firstRename = deferred<Response>();
  const secondRename = deferred<Response>();
  const renameSignals: AbortSignal[] = [];
  const setError = vi.fn();
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'PATCH') {
      renameSignals.push(init.signal as AbortSignal);
      return renameSignals.length === 1 ? firstRename.promise : secondRename.promise;
    }
    return originalFetch(input, init);
  });
  const { result, rerender } = renderHook(
    ({ topic }) => {
      const activity = useActivity();
      return useTopicSession(topic, setError, activity.activity, activity);
    },
    { initialProps: { topic: 'topic-a' } },
  );
  await waitFor(() => expect(result.current.topicReady).toBe(true));

  let first!: Promise<void>;
  act(() => {
    first = result.current.renameConversation('default', 'A title');
  });
  expect(result.current.conversationPending).toBe(true);
  rerender({ topic: 'topic-b' });
  await waitFor(() => expect(result.current.topicReady).toBe(true));
  expect(renameSignals[0].aborted).toBe(true);
  expect(result.current.conversationPending).toBe(false);

  let second!: Promise<void>;
  act(() => {
    second = result.current.renameConversation('default', 'B title');
  });
  expect(result.current.conversationPending).toBe(true);
  firstRename.resolve(new Response(JSON.stringify({ id: 'default', title: 'A title' }), { status: 200 }));
  await act(async () => first);
  expect(result.current.conversationPending).toBe(true);
  expect(result.current.conversations[0]).toEqual({ id: 'default', title: 'Main chat' });

  secondRename.resolve(new Response(JSON.stringify({ id: 'default', title: 'B title' }), { status: 200 }));
  await act(async () => second);
  expect(result.current.conversationPending).toBe(false);
  expect(result.current.conversations[0]).toEqual({ id: 'default', title: 'B title' });
});

test('adopts imported history without clearing same-conversation input and ignores another topic', async () => {
  installFakeApi();
  const setError = vi.fn();
  const { result, rerender } = renderHook(
    ({ topic }) => {
      const activity = useActivity();
      return useTopicSession(topic, setError, activity.activity, activity);
    },
    { initialProps: { topic: 'topic-a' } },
  );
  await waitFor(() => expect(result.current.topicReady).toBe(true));

  const response = deferred<void>();
  const hydrate = response.promise.then(() => {
    result.current.adoptConversationHistory('topic-a', 'default', [{ role: 'user', content: 'Saved snapshot' }], {
      used: 12,
      limit: 1000,
    });
  });
  act(() => result.current.setInput('Typed while import was pending'));
  await act(async () => {
    response.resolve();
    await hydrate;
  });
  expect(result.current.messages).toEqual([{ role: 'user', content: 'Saved snapshot' }]);
  expect(result.current.context).toEqual({ used: 12, limit: 1000 });
  expect(result.current.input).toBe('Typed while import was pending');

  rerender({ topic: 'topic-b' });
  await waitFor(() => expect(result.current.topicReady).toBe(true));
  act(() => {
    result.current.adoptConversationHistory('topic-a', 'default', [{ role: 'user', content: 'Stale snapshot' }], {});
  });
  expect(result.current.messages).not.toContainEqual({ role: 'user', content: 'Stale snapshot' });
  expect(result.current.input).toBe('');
});

test('a captured history adopter cannot update a conversation after switching within the same topic', async () => {
  installFakeApi();
  const setError = vi.fn();
  const { result } = renderHook(() => {
    const activity = useActivity();
    return useTopicSession('topic-a', setError, activity.activity, activity);
  });
  await waitFor(() => expect(result.current.topicReady).toBe(true));
  const adoptDefaultConversation = result.current.adoptConversationHistory;

  let creation!: Promise<void>;
  act(() => {
    creation = result.current.createConversation('Second chat');
  });
  await act(async () => creation);
  await waitFor(() => expect(result.current.conversation).toBe('chat-1'));
  await waitFor(() => expect(result.current.topicReady).toBe(true));

  act(() => {
    adoptDefaultConversation('topic-a', 'default', [{ role: 'user', content: 'Old conversation snapshot' }], {});
  });
  expect(result.current.messages).not.toContainEqual({ role: 'user', content: 'Old conversation snapshot' });
});
