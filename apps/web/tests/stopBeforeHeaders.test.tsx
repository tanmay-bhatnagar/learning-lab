import { flushSync } from 'react-dom';
import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';
import { App } from '../src/App';
import { Composer } from '../src/components/Composer';
import { installFakeApi } from './fakeApi';

describe('stopping before chat response headers', () => {
  test('preserves an admitted user message and reports uncertain history after Stop', async () => {
    const fake = installFakeApi();
    const delegate = fake.fetch;
    let posts = 0;
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/chat') && init?.method === 'POST') {
        posts += 1;
        const body = JSON.parse(String(init.body)) as { message: string };
        fake.messages['topic-a'].push({ role: 'user', content: body.message });
        await new Promise<never>((_resolve, reject) => {
          const abort = () => reject(new DOMException('The operation was aborted.', 'AbortError'));
          if (init.signal?.aborted) abort();
          else init.signal?.addEventListener('abort', abort, { once: true });
        });
      }
      return delegate(input, init);
    });

    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).toBeEnabled());
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Synthetic saved request');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('button', { name: 'Stop response' });
    expect(posts).toBe(1);

    await user.click(screen.getByRole('button', { name: 'Stop response' }));

    await waitFor(() =>
      expect({
        posts,
        draft: (screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement).value,
        visibleSavedUser: document.querySelector('.message-list')?.textContent?.includes('Synthetic saved request'),
        alert: screen.queryByRole('alert')?.textContent,
      }).toEqual({
        posts: 1,
        draft: '',
        visibleSavedUser: true,
        alert: expect.stringMatching(/stopped|saved|history|confirm/i),
      }),
    );
  });

  test('a Stop activation cannot submit if its button becomes Send synchronously', async () => {
    let submissions = 0;

    function Harness() {
      const [sending, setSending] = useState(true);
      return (
        <Composer
          input="Synthetic draft"
          sending={sending}
          busy={sending}
          topicReady
          follow
          hasMessages
          selectedCount={0}
          extraSearch={false}
          extraSearchAvailable={false}
          activeModel={{ id: 'local', name: 'local', thinking: { type: 'none' } }}
          modelError=""
          meter={{ limit: 32768, percent: 0, label: 'Context tokens' }}
          bottomRef={{ current: null }}
          thinkValue={() => undefined}
          onInputChange={() => undefined}
          onSend={(event) => {
            event.preventDefault();
            submissions += 1;
          }}
          onStop={() => flushSync(() => setSending(false))}
          onFollowLatest={() => undefined}
          onOpenFiles={() => undefined}
          onOpenSettings={() => undefined}
          onThinkChange={() => undefined}
          onRetryConnection={() => undefined}
          onExtraSearchChange={() => undefined}
        />
      );
    }

    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Stop response' }));

    expect(submissions).toBe(0);
  });
});
