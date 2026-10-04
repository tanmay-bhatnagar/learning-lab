import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';
import { App } from '../src/App';
import { ConversationBar } from '../src/components/ConversationBar';
import { installFakeApi } from './fakeApi';

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900, writable: true });
});

test('creates, renames and switches independent chats within one topic', async () => {
  installFakeApi();
  const user = userEvent.setup();
  render(<App />);
  expect(await screen.findByText('Hello from Topic A')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'New chat' }));
  await user.type(screen.getByRole('textbox', { name: 'Conversation title' }), 'Paper questions');
  await user.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(screen.queryByText('Hello from Topic A')).not.toBeInTheDocument());
  expect(screen.getByRole('combobox', { name: 'Conversation' })).toHaveValue('chat-1');
  await user.click(screen.getByRole('button', { name: 'Rename' }));
  await user.clear(screen.getByRole('textbox', { name: 'Conversation title' }));
  await user.type(screen.getByRole('textbox', { name: 'Conversation title' }), 'Deep dive');
  await user.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByRole('option', { name: 'Deep dive' })).toBeInTheDocument();
  await user.selectOptions(screen.getByRole('combobox', { name: 'Conversation' }), 'default');
  expect(await screen.findByText('Hello from Topic A')).toBeInTheDocument();
});

test('keeps an unsaved topic learning goal while switching conversations', async () => {
  installFakeApi();
  const user = userEvent.setup();
  render(<App />);
  const goal = await screen.findByLabelText(/Your learning goal for this topic/);
  await user.clear(goal);
  await user.type(goal, 'Explore the paper carefully');
  await user.click(screen.getByRole('button', { name: 'New chat' }));
  await user.type(screen.getByRole('textbox', { name: 'Conversation title' }), 'Paper questions');
  await user.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Conversation' })).toHaveValue('chat-1'));
  expect(await screen.findByLabelText(/Your learning goal for this topic/)).toHaveValue('Explore the paper carefully');
  await user.selectOptions(screen.getByRole('combobox', { name: 'Conversation' }), 'default');
  expect(await screen.findByLabelText(/Your learning goal for this topic/)).toHaveValue('Explore the paper carefully');
});

test('discards a rename draft when switching conversations', async () => {
  installFakeApi();
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Hello from Topic A');
  await user.click(screen.getByRole('button', { name: 'New chat' }));
  await user.type(screen.getByRole('textbox', { name: 'Conversation title' }), 'Second chat');
  await user.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Conversation' })).toHaveValue('chat-1'));
  await user.click(screen.getByRole('button', { name: 'Rename' }));
  await user.clear(screen.getByRole('textbox', { name: 'Conversation title' }));
  await user.type(screen.getByRole('textbox', { name: 'Conversation title' }), 'Stale rename');
  await user.selectOptions(screen.getByRole('combobox', { name: 'Conversation' }), 'default');
  expect(screen.queryByRole('textbox', { name: 'Conversation title' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Rename' }));
  expect(screen.getByRole('textbox', { name: 'Conversation title' })).toHaveValue('Main chat');
});

test('discards a conversation editor when switching topics', async () => {
  installFakeApi();
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Hello from Topic A');
  await user.click(screen.getByRole('button', { name: 'Rename' }));
  await user.clear(screen.getByRole('textbox', { name: 'Conversation title' }));
  await user.type(screen.getByRole('textbox', { name: 'Conversation title' }), 'Topic A draft');
  await user.click(screen.getByRole('button', { name: 'Topic B' }));
  await screen.findByText('Hello from Topic B');
  expect(screen.queryByRole('textbox', { name: 'Conversation title' })).not.toBeInTheDocument();
});

test('a disabled conversation editor cannot submit create or rename', () => {
  const onCreate = vi.fn();
  const onRename = vi.fn();
  const props = {
    conversations: [{ id: 'default', title: 'Default' }],
    activeId: 'default',
    onSelect: vi.fn(),
    onCreate,
    onRename,
  };
  const { rerender } = render(<ConversationBar {...props} disabled={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'New chat' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Conversation title' }), { target: { value: 'Draft' } });
  rerender(<ConversationBar {...props} disabled />);
  const form = screen.getByRole('textbox', { name: 'Conversation title' }).closest('form');
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  fireEvent.submit(form!);
  expect(onCreate).not.toHaveBeenCalled();
  expect(onRename).not.toHaveBeenCalled();

  rerender(<ConversationBar {...props} disabled={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Conversation title' }), { target: { value: 'Renamed' } });
  rerender(<ConversationBar {...props} disabled />);
  fireEvent.submit(screen.getByRole('textbox', { name: 'Conversation title' }).closest('form')!);
  expect(onRename).not.toHaveBeenCalled();
});
