import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, test, vi } from 'vitest';
import mapFixture from './fixtures/documentMapApi.json';
import summaryContract from './fixtures/document-summary-import-contract.json';
import { mapSectionResponseSchema } from '../src/api/documentMap';
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
  {
    id: 'second-paper',
    name: 'Second synthetic paper.pdf',
    status: 'ready',
    parser: 'docling',
    docling_name: 'second-paper.docling.json',
  },
  { id: 'markdown-file', name: 'Markdown.pdf', status: 'ready', parser: 'markitdown' },
  { id: 'processing-file', name: 'Processing.pdf', status: 'processing', parser: 'docling' },
];

function installMapApi(
  options: { stale?: boolean; invalid?: boolean; deferFirstGet?: boolean; deferBuild?: boolean; deferSummary?: boolean } = {},
) {
  const base = createFakeApi({ files: { 'topic-a': otherFiles } });
  vi.stubGlobal('fetch', base.fetch);
  const mapCalls: { method: string; path: string }[] = [];
  const summaryCalls: { body: Record<string, unknown>; signal?: AbortSignal }[] = [];
  const importCalls: { path: string; body: Record<string, unknown> }[] = [];
  let built = false;
  let latestSummary: Record<string, unknown> | null = null;
  let latestAttempt: Record<string, unknown> | null = null;
  let firstGetStarted = false;
  let releaseFirstGet: (() => void) | null = null;
  let releaseBuild: (() => void) | null = null;
  let releaseSummary: (() => void) | null = null;
  const fakeFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const parsed = new URL(url, 'http://test.local');
    const summaryMatch = parsed.pathname.match(
      /^\/api\/topics\/([^/]+)\/files\/([^/]+)\/map\/sections\/([^/]+)\/summary$/,
    );
    if (summaryMatch) {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
      summaryCalls.push({ body, signal: init?.signal as AbortSignal | undefined });
      const startEvent = summaryContract.summary_events[0];
      const doneEvent = summaryContract.summary_events[3];
      const attemptId = `summary-attempt-${summaryCalls.length}`;
      const summary = {
        ...summaryContract.summary,
        id: attemptId,
        revision: body.revision,
        section_id: decodeURIComponent(summaryMatch[3]),
      };
      const attempt = {
        ...startEvent.attempt,
        id: attemptId,
        revision: body.revision,
        section_id: decodeURIComponent(summaryMatch[3]),
      };
      const events = [
        { ...startEvent, attempt_id: attemptId, revision: body.revision, section_id: decodeURIComponent(summaryMatch[3]), attempt },
        { ...summaryContract.summary_events[2], attempt_id: attemptId },
        {
          ...doneEvent,
          attempt_id: attemptId,
          summary,
          attempt: { ...attempt, status: 'completed', actual_model: 'fake-local-model', finished_at: summary.created_at, content: summary.content },
        },
      ];
      latestSummary = summary;
      latestAttempt = events[2].attempt;
      if (options.deferSummary) {
        let finish: (() => void) | null = null;
        const done = new Promise<void>((resolve) => {
          finish = resolve;
        });
        releaseSummary = () => finish?.();
        const stream = new ReadableStream<Uint8Array>({
          async start(controller) {
            controller.enqueue(new TextEncoder().encode(`${JSON.stringify(events[0])}\n${JSON.stringify(events[1])}\n`));
            await done;
            controller.enqueue(new TextEncoder().encode(`${JSON.stringify(events[2])}\n`));
            controller.close();
          },
        });
        return new Response(stream, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } });
      }
      return new Response(`${events.map((event) => JSON.stringify(event)).join('\n')}\n`, {
        status: 200,
        headers: { 'Content-Type': 'application/x-ndjson' },
      });
    }
    const importMatch = parsed.pathname.match(/^\/api\/topics\/([^/]+)\/conversations\/([^/]+)\/summary-imports$/);
    if (importMatch) {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
      importCalls.push({ path: parsed.pathname, body });
      const sourceMessage = summaryContract.import.message;
      const message = {
        ...sourceMessage,
        summary_import: {
          ...sourceMessage.summary_import,
          file_id: body.file_id,
          revision: body.revision,
          section_id: body.section_id,
          summary_id: body.summary_id,
        },
      };
      return new Response(
        JSON.stringify({ conversation_id: decodeURIComponent(importMatch[2]), imported: true, message, messages: [message] }),
        { status: 200 },
      );
    }
    const match = parsed.pathname.match(/^\/api\/topics\/([^/]+)\/files\/([^/]+)\/map(?:\/sections\/([^/]+))?$/);
    if (!match) return base.fetch(input, init);
    const method = (init?.method ?? 'GET').toUpperCase();
    mapCalls.push({ method, path: parsed.pathname });
    if (match[3]) {
      return new Response(JSON.stringify(mapFixture.section_response), { status: 200 });
    }
    if (method === 'POST') {
      built = true;
      if (options.deferBuild) {
        return new Promise<Response>((resolve) => {
          releaseBuild = () => resolve(new Response(JSON.stringify(mapFixture.build_response), { status: 200 }));
        });
      }
      return new Response(JSON.stringify(mapFixture.build_response), { status: 200 });
    }
    if (options.deferFirstGet && match[2] === 'synthetic-paper' && !firstGetStarted) {
      firstGetStarted = true;
      return new Promise<Response>((resolve) => {
        releaseFirstGet = () => resolve(new Response(JSON.stringify(mapFixture.build_response), { status: 200 }));
      });
    }
    if (match[2] === 'second-paper') {
      const alternate = JSON.parse(JSON.stringify(mapFixture.build_response));
      alternate.map.sections[0].title = 'Alternate outline';
      return new Response(JSON.stringify(alternate), { status: 200 });
    }
    const response = options.invalid
      ? { status: 'ready', map: { wrong: true } }
      : options.stale
        ? { ...mapFixture.build_response, status: 'stale' }
        : built
          ? (() => {
              const saved = JSON.parse(JSON.stringify(mapFixture.build_response));
              if (latestSummary) saved.map.sections[0].last_summary = latestSummary;
              if (latestAttempt) saved.map.sections[0].latest_attempt = latestAttempt;
              return saved;
            })()
          : { status: 'not_built', map: null };
    return new Response(JSON.stringify(response), { status: 200 });
  };
  vi.stubGlobal('fetch', fakeFetch);
  return {
    mapCalls,
    summaryCalls,
    importCalls,
    resolveFirstGet: () => releaseFirstGet?.(),
    resolveBuild: () => releaseBuild?.(),
    resolveSummary: () => releaseSummary?.(),
  };
}

async function waitForReady() {
  await waitFor(() => expect(screen.queryByText(/Connecting to your workspace/i)).not.toBeInTheDocument());
}

afterEach(() => vi.unstubAllGlobals());

describe('document map navigation', () => {
  test('section payload schema accepts stale sections returned by the backend', () => {
    const staleSection = { ...mapFixture.section_response, status: 'stale' };
    expect(mapSectionResponseSchema.safeParse(staleSection).success).toBe(true);
  });

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
    await user.click(screen.getByRole('button', { name: 'Map' }));
    expect(screen.getByRole('combobox', { name: /PDF for map/i })).toHaveValue('synthetic-paper');
  });

  test('file changes ignore an outstanding response from the previous file', async () => {
    const { resolveFirstGet } = installMapApi({ deferFirstGet: true });
    const user = userEvent.setup();
    render(<App />);
    await waitForReady();
    await user.click(screen.getByRole('button', { name: 'Map' }));
    const picker = screen.getByRole('combobox', { name: /PDF for map/i });
    await user.selectOptions(picker, 'synthetic-paper');
    await waitFor(() => expect(resolveFirstGet).toBeDefined());
    await user.selectOptions(picker, 'second-paper');
    expect(await screen.findByText('Alternate outline')).toBeInTheDocument();
    resolveFirstGet();
    await waitFor(() => expect(screen.getByText('Alternate outline')).toBeInTheDocument());
    expect(screen.queryByText('Methods')).not.toBeInTheDocument();
  });

  test('a rapid second build click cannot overlap the first request', async () => {
    const { mapCalls, resolveBuild } = installMapApi({ deferBuild: true });
    const user = userEvent.setup();
    render(<App />);
    await waitForReady();
    await user.click(screen.getByRole('button', { name: 'Map' }));
    await user.selectOptions(screen.getByRole('combobox', { name: /PDF for map/i }), 'synthetic-paper');
    await screen.findByRole('button', { name: /Build outline/i });
    const buildButton = screen.getByRole('button', { name: /Build outline/i });
    fireEvent.click(buildButton);
    fireEvent.click(buildButton);
    await waitFor(() => expect(mapCalls.filter((call) => call.method === 'POST')).toHaveLength(1));
    expect(buildButton).toBeDisabled();
    resolveBuild();
    expect(await screen.findByText('Methods')).toBeInTheDocument();
  });

  test('summary generation survives a tab return while the map refreshes and Stop is available immediately', async () => {
    const { summaryCalls, resolveSummary } = installMapApi({ deferSummary: true });
    const user = userEvent.setup();
    render(<App />);
    await waitForReady();
    await user.click(screen.getByRole('button', { name: 'Map' }));
    await user.selectOptions(screen.getByRole('combobox', { name: /PDF for map/i }), 'synthetic-paper');
    await user.click(await screen.findByRole('button', { name: /Build outline/i }));
    await user.click((await screen.findAllByRole('button', { name: 'Select for summary' }))[0]);
    await user.click(screen.getByRole('button', { name: 'Generate summary' }));
    expect(screen.getByRole('button', { name: /Stop summary/i })).toBeInTheDocument();
    await waitFor(() => expect(summaryCalls).toHaveLength(1));

    await user.click(screen.getByRole('button', { name: /Attached files/i }));
    await user.click(screen.getByRole('button', { name: 'Map' }));
    expect(screen.getByRole('button', { name: /Stop summary/i })).toBeInTheDocument();
    resolveSummary();
    expect(await screen.findByText('A synthetic statement [S1].')).toBeInTheDocument();
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

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid .*map/i);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
