import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test } from 'vitest';
import { App } from '../src/App';
import { installFakeApi } from './fakeApi';

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900, writable: true });
});

test('sending a message resumes following the latest reply after scrolling up', async () => {
  installFakeApi();
  const user = userEvent.setup();
  render(<App />);
  await waitFor(() => expect(screen.getByText('Hello from Topic A')).toBeInTheDocument());

  const conversation = document.querySelector('.conversation') as HTMLElement;
  Object.defineProperty(conversation, 'scrollHeight', { configurable: true, value: 2000 });
  Object.defineProperty(conversation, 'clientHeight', { configurable: true, value: 400 });
  Object.defineProperty(conversation, 'scrollTop', { configurable: true, value: 0 });
  fireEvent.scroll(conversation);
  expect(await screen.findByRole('button', { name: /Latest/i })).toBeInTheDocument();

  await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Follow me');
  await user.click(screen.getByRole('button', { name: 'Send message' }));
  await waitFor(() => expect(screen.getByText(/Echo: Follow me/)).toBeInTheDocument());
  expect(screen.queryByRole('button', { name: /Latest/i })).not.toBeInTheDocument();
});
