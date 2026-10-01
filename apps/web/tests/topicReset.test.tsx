import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, test } from 'vitest';
import { App } from '../src/App';
import { installFakeApi, type StreamScript } from './fakeApi';

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900, writable: true });
});

const errorStream: StreamScript = async function* () {
  yield { type: 'token', text: 'Started' };
  yield { type: 'error', message: 'Model unavailable' };
};

async function renderWithBannerError() {
  installFakeApi({ stream: errorStream });
  const user = userEvent.setup();
  render(<App />);
  await waitFor(() => expect(screen.queryByText(/Connecting to your workspace/i)).not.toBeInTheDocument());
  await waitFor(() => expect(screen.getByRole('button', { name: 'Topic A' })).toBeInTheDocument());
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).not.toBeDisabled());
  await waitFor(() => expect(screen.getByText('Hello from Topic A')).toBeInTheDocument());
  await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Fail please');
  await user.click(screen.getByRole('button', { name: 'Send message' }));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/Model unavailable/i));
  return user;
}

describe('topic load resets', () => {
  test('Reload clears the error banner and reloads the topic', async () => {
    const user = await renderWithBannerError();
    await user.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Reload' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(screen.getByText('Hello from Topic A')).toBeInTheDocument();
    expect(screen.queryByText('Started')).not.toBeInTheDocument();
  });

  test('switching topics clears the error banner', async () => {
    const user = await renderWithBannerError();
    await user.click(screen.getByRole('button', { name: 'Topic B' }));
    await waitFor(() => expect(screen.getByText('Hello from Topic B')).toBeInTheDocument());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  test('Reload closes an open file preview', async () => {
    const user = await renderWithBannerError();
    const tabs = document.querySelector('.tabs') as HTMLElement;
    await user.click(within(tabs).getByRole('button', { name: /Attached files/i }));
    await user.click(await screen.findByRole('button', { name: /Inspect/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Close preview' })).toBeInTheDocument());
    await user.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Reload' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Close preview' })).not.toBeInTheDocument());
  });
});
