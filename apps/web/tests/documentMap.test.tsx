import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, test, vi } from 'vitest';
import mapFixture from './fixtures/documentMapApi.json';
import { App } from '../src/App';
import type { LabFile } from '../src/api/types';
import { createFakeApi } from './fakeApi';

const mapFile: LabFile = {
  id: 'synthetic-paper',
  name: 'Synthetic paper.pdf',
  status: 'ready',
  parser: 'docling',
  page_count: 2,
  docling_name: 'synthetic-paper.docling.json',
};

const otherFiles: LabFile[] = [
  mapFile,
  { id: 'markdown-file', name: 'Markdown.pdf', status: 'ready', parser: 'markitdown' },
  { id: 'processing-file', name: 'Processing.pdf', status: 'processing', parser: 'docling' },
];

function installMapApi(options: { stale?: boolean; invalid?: boolean } = {}) {
  const base = createFakeApi({ files: { 'topic-a': otherFiles } });
  vi.stubGlobal('fetch', base.fetch);
  const mapCalls: { method: string; path: string }[] = [];
  let built = false;
  const fakeFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const parsed = new URL(url, 'http://test.local');
    const match = parsed.pathname.match(/^\/api\/topics\/([^/]+)\/files\/([^/]+)\/map(?:\/sections\/([^/]+))?$/);
    if (!match) return base.fetch(input, init);
    const method = (init?.method ?? 'GET').toUpperCase();
    mapCalls.push({ method, path: parsed.pathname });
    if (match[3]) {
      return new Response(JSON.stringify(mapFixture.section_response), { status: 200 });
    }
    if (method === 'POST') {
      built = true;
      return new Response(JSON.stringify(mapFixture.build_response), { status: 200 });
    }
    const response = options.invalid
      ? { status: 'ready', map: { wrong: true } }
      : options.stale
      ? { ...mapFixture.build_response, status: 'stale' }
      : built
        ? mapFixture.build_response
        : { status: 'not_built', map: null };
    return new Response(JSON.stringify(response), { status: 200 });
  };
  vi.stubGlobal('fetch', fakeFetch);
  return { mapCalls };
}

async function waitForReady() {
  await waitFor(() => expect(screen.queryByText(/Connecting to your workspace/i)).not.toBeInTheDocument());
}

afterEach(() => vi.unstubAllGlobals());

describe('document map navigation', () => {
  test('map selection is independent and builds only after an explicit request', async () => {
    const { mapCalls } = installMapApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForReady();

    await user.click(screen.getByRole('button', { name: 'Map' }));
    expect(mapCalls).toEqual([]);
    expect(screen.getByRole('button', { name: /Build outline/i })).toBeDisabled();

    const filePicker = screen.getByRole('combobox', { name: /PDF for map/i });
    expect(within(filePicker).getByRole('option', { name: /Markdown.*not supported/i })).toBeDisabled();
    expect(within(filePicker).getByRole('option', { name: /Processing.*not ready/i })).toBeDisabled();
    await user.selectOptions(filePicker, 'synthetic-paper');
    await screen.findByRole('button', { name: /Build outline/i });
    await waitFor(() => expect(mapCalls.filter((call) => call.method === 'GET')).toHaveLength(1));
    expect(mapCalls.some((call) => call.method === 'POST')).toBe(false);

    await user.click(screen.getByRole('button', { name: /Build outline/i }));
    expect(await screen.findByText('Methods')).toBeInTheDocument();
    expect(await screen.findByText('Training')).toBeInTheDocument();
    expect(mapCalls.filter((call) => call.method === 'POST')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /Generate summary/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Attached files/i }));
    expect(screen.getByRole('checkbox', { name: 'Include Synthetic paper.pdf in chat' })).not.toBeChecked();
  });

  test('stale outline offers explicit rebuild and displays original page links', async () => {
    const { mapCalls } = installMapApi({ stale: true });
    const user = userEvent.setup();
    render(<App />);
    await waitForReady();
    await user.click(screen.getByRole('button', { name: 'Map' }));
    await user.selectOptions(screen.getByRole('combobox', { name: /PDF for map/i }), 'synthetic-paper');

    expect(await screen.findByText(/This outline is out of date/i)).toBeInTheDocument();
    const rebuild = screen.getByRole('button', { name: /Rebuild outline/i });
    expect(rebuild).toBeEnabled();
    expect(screen.getAllByRole('link', { name: 'Page 1' })[0]).toHaveAttribute(
      'href',
      '/api/topics/topic-a/files/synthetic-paper/original#page=1',
    );
    await user.click(rebuild);
    await waitFor(() => expect(mapCalls.filter((call) => call.method === 'POST')).toHaveLength(1));
  });

  test('invalid saved map payload is shown as a retryable error', async () => {
    installMapApi({ invalid: true });
    const user = userEvent.setup();
    render(<App />);
    await waitForReady();
    await user.click(screen.getByRole('button', { name: 'Map' }));
    await user.selectOptions(screen.getByRole('combobox', { name: /PDF for map/i }), 'synthetic-paper');

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid response/i);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
