import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { App } from '../src/App';
import { installFakeApi, pdfFile, type StreamScript } from './fakeApi';
import { MAX_PDF_BYTES } from '../src/uploads';

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900, writable: true });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function waitForAppReady() {
  await waitFor(() => expect(screen.queryByText(/Connecting to your workspace/i)).not.toBeInTheDocument());
  await waitFor(() => expect(screen.getByRole('button', { name: 'Topic A' })).toBeInTheDocument());
}

async function openFilesTab(user: ReturnType<typeof userEvent.setup>) {
  const tabs = document.querySelector('.tabs') as HTMLElement | null;
  if (!tabs) throw new Error('Workspace tabs missing');
  await user.click(within(tabs).getByRole('button', { name: /Attached files/i }));
  await waitFor(() => expect(screen.getByText(/Your reading material/i)).toBeInTheDocument());
}

function fileInput() {
  return document.querySelector('input[type="file"]') as HTMLInputElement;
}

function asFileList(files: File[]): FileList {
  const list = {
    length: files.length,
    item: (index: number) => files[index] ?? null,
    *[Symbol.iterator]() {
      yield* files;
    },
  };
  files.forEach((file, index) => {
    Object.defineProperty(list, index, { value: file, enumerable: true });
  });
  return list as FileList;
}

function uploadThroughInput(files: File[]) {
  const input = fileInput();
  const list = asFileList(files);
  Object.defineProperty(input, 'files', { configurable: true, value: list });
  fireEvent.change(input, { target: { files: list } });
}

describe('App characterization', () => {
  test('topic switch resets messages, files, selection, goal and input; goal save blocked until ready', async () => {
    installFakeApi({
      messages: {
        'topic-a': [{ role: 'user', content: 'Message A' }],
        'topic-b': [{ role: 'user', content: 'Message B' }],
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    expect(screen.getByText('Message A')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Learn A')).toBeInTheDocument();

    const goalField = screen.getByPlaceholderText(/What would you like to learn/i);
    await user.clear(goalField);
    await user.type(goalField, 'Draft goal not saved');

    await user.click(screen.getByRole('button', { name: 'Topic B' }));
    await waitFor(() => expect(screen.getByText('Message B')).toBeInTheDocument());
    expect(screen.queryByText('Message A')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('Learn B')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Draft goal not saved')).not.toBeInTheDocument();

    await user.clear(screen.getByPlaceholderText(/What would you like to learn/i));
    await user.type(screen.getByPlaceholderText(/What would you like to learn/i), 'New goal');
    await user.click(screen.getByRole('button', { name: /Save learning goal/i }));
    await waitFor(() => expect(screen.getByText(/Learning goal saved/i)).toBeInTheDocument());
  });

  test('send streams thinking and token events; stop aborts with partial text', async () => {
    const slowStream: StreamScript = async function* (_body, signal) {
      yield { type: 'thinking', text: 'Hmm' };
      await new Promise((resolve) => setTimeout(resolve, 30));
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      yield { type: 'token', text: 'Partial' };
      await new Promise((resolve) => setTimeout(resolve, 300));
      yield { type: 'token', text: ' answer' };
      yield { type: 'done', model: 'qwen3.5:9b-q4_K_M', context: { used: 10, limit: 32768 } };
    };
    installFakeApi({ stream: slowStream });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Hello stream');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => expect(screen.getByText(/Hmm/)).toBeInTheDocument());
    await user.click(await screen.findByRole('button', { name: 'Stop response' }));

    await waitFor(() => expect(screen.getByText(/Response stopped/i)).toBeInTheDocument());
    expect(screen.getByText(/Partial/)).toBeInTheDocument();
    expect(screen.getByText(/Response incomplete/i)).toBeInTheDocument();
  });

  test('stream error marks assistant message incomplete', async () => {
    const errorStream: StreamScript = async function* () {
      yield { type: 'token', text: 'Started' };
      yield { type: 'error', message: 'Model unavailable' };
    };
    installFakeApi({ stream: errorStream });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Fail please');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => expect(screen.getByText(/Model unavailable/i)).toBeInTheDocument());
    expect(screen.getByText(/Response incomplete/i)).toBeInTheDocument();
    expect(screen.getByText('Started')).toBeInTheDocument();
  });

  test('upload rejects non-PDF and oversize files', async () => {
    installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await openFilesTab(user);

    const zone = screen.getByRole('button', { name: /Drop PDFs here/i });
    fireEvent.drop(zone, {
      dataTransfer: { files: asFileList([new File(['hello'], 'notes.txt', { type: 'text/plain' })]), types: ['Files'] },
    });
    await waitFor(() => expect(screen.getAllByText(/not a PDF/i).length).toBeGreaterThan(0));

    const big = pdfFile('big.pdf', '%PDF-' + 'x'.repeat(MAX_PDF_BYTES));
    fireEvent.drop(zone, { dataTransfer: { files: asFileList([big]), types: ['Files'] } });
    await waitFor(() => expect(screen.getAllByText(/25 MiB/i).length).toBeGreaterThan(0));
  });

  test('upload blocked while chat is sending', async () => {
    const slowStream: StreamScript = async function* () {
      yield { type: 'thinking', text: '…' };
      await new Promise((resolve) => setTimeout(resolve, 500));
      yield { type: 'done', context: { used: 1, limit: 32768 } };
    };
    installFakeApi({ stream: slowStream });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'busy');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('button', { name: 'Stop response' });
    await openFilesTab(user);
    uploadThroughInput([pdfFile('blocked.pdf')]);
    await waitFor(() => expect(screen.getByText(/Finish the current action/i)).toBeInTheDocument());
  });

  test('drag-and-drop shows feedback and accepts PDFs', async () => {
    installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await openFilesTab(user);

    const zone = screen.getByRole('button', { name: /Drop PDFs here/i });
    fireEvent.dragEnter(zone, { dataTransfer: { types: ['Files'], dropEffect: 'copy' } });
    expect(screen.getByText(/Release to add your PDFs/i)).toBeInTheDocument();

    fireEvent.drop(zone, {
      dataTransfer: { files: [pdfFile('dropped.pdf')], types: ['Files'] },
    });
    await waitFor(() => expect(screen.getByText('dropped.pdf')).toBeInTheDocument());
  });

  test('model select reports server mismatch', async () => {
    const altModel = {
      id: 'llama3:8b',
      name: 'llama3:8b',
      display_name: 'Llama 3 · 8B',
      thinking: { type: 'none' as const },
    };
    const qwen = { id: 'qwen3.5:9b-q4_K_M', name: 'qwen3.5:9b-q4_K_M', thinking: { type: 'toggle' as const } };
    const fake = installFakeApi({ models: [altModel, qwen] });
    fake.setOnSettingsPut((next) => ({ ...next, model: qwen.id }));
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.click(screen.getByRole('button', { name: /Settings/i }));
    await user.selectOptions(screen.getByLabelText(/Default model/i), 'llama3:8b');
    await waitFor(() => expect(screen.getByText(/server did not apply the selected model/i)).toBeInTheDocument());
  });

  test('model select persists when server accepts', async () => {
    const altModel = {
      id: 'llama3:8b',
      name: 'llama3:8b',
      display_name: 'Llama 3 · 8B',
      thinking: { type: 'none' as const },
    };
    const qwen = { id: 'qwen3.5:9b-q4_K_M', name: 'qwen3.5:9b-q4_K_M', thinking: { type: 'toggle' as const } };
    const fake = installFakeApi({ models: [altModel, qwen] });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.click(screen.getByRole('button', { name: /Settings/i }));
    await user.selectOptions(screen.getByLabelText(/Default model/i), 'llama3:8b');
    await waitFor(() => expect(screen.getByText(/Llama 3 · 8B selected/i)).toBeInTheDocument());
    expect(fake.settings.model).toBe('llama3:8b');
  });

  test('settings save persists draft values', async () => {
    const fake = installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.click(screen.getByRole('button', { name: /Settings/i }));
    const contextInput = screen.getByLabelText(/Context limit/i);
    await user.clear(contextInput);
    await user.type(contextInput, '4096');
    await user.click(screen.getByRole('button', { name: /Save settings/i }));
    await waitFor(() => expect(screen.getByText(/Settings saved/i)).toBeInTheDocument());
    expect(fake.settings.context_limit).toBe(4096);
  });

  test('file preview loads markdown and switches to original tab', async () => {
    const fake = installFakeApi();
    fake.setMarkdown('file-1', '# Preview markdown\n\nBody text.');
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await openFilesTab(user);

    await user.click(screen.getByRole('button', { name: /Inspect/i }));
    await waitFor(() => expect(screen.getByText('Preview markdown')).toBeInTheDocument());
    expect(screen.getByText(/Body text/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Original PDF' }));
    expect(screen.getByTitle(/Original PDF: paper-a.pdf/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close preview' }));
    expect(screen.queryByText('Preview markdown')).not.toBeInTheDocument();
  });

  test('Refresh files re-fetches the file list without clearing conversation or input', async () => {
    const fake = installFakeApi({
      messages: { 'topic-a': [{ role: 'user', content: 'Keep this?' }] },
      files: {
        'topic-a': [
          {
            id: 'file-1',
            name: 'paper-a.pdf',
            status: 'ready',
            parser: 'docling',
            index_status: 'ready',
            index_mode: 'hybrid',
          },
          {
            id: 'file-2',
            name: 'paper-aux.pdf',
            status: 'ready',
            parser: 'docling',
            index_status: 'ready',
            index_mode: 'hybrid',
          },
        ],
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).not.toBeDisabled());
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'typed before refresh');

    await openFilesTab(user);
    const checkboxA = screen.getByRole('checkbox', { name: /paper-a.pdf/i });
    const checkboxB = screen.getByRole('checkbox', { name: /paper-aux.pdf/i });
    await user.click(checkboxA);
    await user.click(checkboxB);
    expect(checkboxA).toBeChecked();
    expect(checkboxB).toBeChecked();

    fake.removeFile('topic-a', 'file-1');
    await user.click(screen.getByRole('button', { name: 'Refresh files' }));
    await waitFor(() => expect(screen.queryByText('paper-a.pdf')).not.toBeInTheDocument());
    expect(screen.getByRole('checkbox', { name: /paper-aux.pdf/i })).toBeChecked();

    const tabs = document.querySelector('.tabs') as HTMLElement | null;
    if (!tabs) throw new Error('Workspace tabs missing');
    await user.click(within(tabs).getByRole('button', { name: /Conversation/i }));
    expect(screen.getByText('Keep this?')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('typed before refresh');
    expect(screen.queryByRole('checkbox', { name: /paper-a.pdf/i })).not.toBeInTheDocument();
  });

  test('shows thinking preference storage errors', async () => {
    installFakeApi();
    const original = window.localStorage.setItem.bind(window.localStorage);
    const setItem = vi.spyOn(window.localStorage, 'setItem').mockImplementation((key, value) => {
      if (key === 'lab-thinking') throw new Error('quota');
      original(key, value);
    });
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Thinking preferences could not be saved/i)).toBeInTheDocument());
    setItem.mockRestore();
  });

  test('creates a topic while a chat reply is streaming without stale stream writes', async () => {
    const fake = installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.click(screen.getByRole('button', { name: 'Create topic' }));
    await user.type(screen.getByPlaceholderText(/Understanding neural networks/i), 'Stream topic');

    fake.pauseNextChatStream();
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Hello while modal open');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('button', { name: 'Stop response' });

    const dialog = screen.getByRole('dialog', { name: /Make room for a new topic/i });
    await user.click(within(dialog).getByRole('button', { name: /^Create topic$/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Stream topic' })).toBeInTheDocument());
    expect(fake.topicPostCount).toBe(1);

    fake.releaseChatStream();
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Stop response' })).not.toBeInTheDocument(), {
      timeout: 3000,
    });

    expect(screen.queryByText(/Echo:/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Hello while modal open')).not.toBeInTheDocument();
  });

  test('Refresh files ignores stale response after topic switch', async () => {
    const fake = installFakeApi({
      files: {
        'topic-a': [{ id: 'file-1', name: 'paper-a.pdf', status: 'ready', parser: 'docling' }],
        'topic-b': [{ id: 'file-2', name: 'paper-b.pdf', status: 'ready', parser: 'docling' }],
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await openFilesTab(user);
    fake.pauseNextFilesGet('topic-a');
    void user.click(screen.getByRole('button', { name: 'Refresh files' }));
    await user.click(screen.getByRole('button', { name: 'Topic B' }));
    await waitFor(() => expect(screen.getByText('paper-b.pdf')).toBeInTheDocument());
    fake.releaseFilesGet();
    await waitFor(() => expect(screen.getByText('paper-b.pdf')).toBeInTheDocument());
    expect(screen.queryByText('paper-a.pdf')).not.toBeInTheDocument();
  });
});
