import { afterEach, describe, expect, test, vi } from 'vitest';
import contract from './fixtures/document-summary-import-contract.json';
import {
  savedSummarySchema,
  summaryImportResponseSchema,
  streamDocumentSummary,
  type SummaryStreamEvent,
} from '../src/api/documentMap';

afterEach(() => vi.unstubAllGlobals());

describe('document summary wire contract', () => {
  test('accepts actual saved-summary and import payloads captured from the backend', () => {
    expect(savedSummarySchema.parse(contract.summary).content).toContain('[S1]');
    expect(summaryImportResponseSchema.parse(contract.import).imported).toBe(true);
  });

  test('dedicated decoder handles chunk boundaries and preserves event identity', async () => {
    const [started, , token, done] = contract.summary_events;
    const chunks = [
      `${JSON.stringify(started)}\n`,
      `${JSON.stringify(token)}\n${JSON.stringify(done)}\n`,
    ];
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(new TextEncoder().encode(chunks[0].slice(0, 19)));
              controller.enqueue(new TextEncoder().encode(chunks[0].slice(19) + chunks[1]));
              controller.close();
            },
          }),
          { status: 200 },
        ),
      ),
    );
    const events: SummaryStreamEvent[] = [];

    await streamDocumentSummary('/summary', {}, new AbortController().signal, (event) => events.push(event));

    expect(events.map((event) => event.type)).toEqual(['started', 'token', 'done']);
    expect(events[1]).toMatchObject({ attempt_id: started.attempt_id, text: token.text });
  });

  test('invalid events and EOF without done fail visibly', async () => {
    const badFetch = (line: string) => {
      vi.stubGlobal('fetch', vi.fn(async () => new Response(line, { status: 200 })));
    };
    badFetch(`${JSON.stringify({ ...contract.summary_events[0], type: 'token', text: 4 })}\n`);
    await expect(streamDocumentSummary('/summary', {}, new AbortController().signal, () => {})).rejects.toThrow();
    badFetch(`${JSON.stringify(contract.summary_events[0])}\n`);
    await expect(streamDocumentSummary('/summary', {}, new AbortController().signal, () => {})).rejects.toThrow(/ended before/i);
  });
});
