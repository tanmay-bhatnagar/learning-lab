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
    const chunks = [
      '{"type":"started","attempt_id":"attempt-1","revision":"rev","section_id":"sec","attempt":{}}\n',
      '{"type":"token","attempt_id":"attempt-1","text":"hello"}\n{"type":"done","attempt_id":"attempt-1","summary":{},"attempt":{}}\n',
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
    expect(events[1]).toMatchObject({ attempt_id: 'attempt-1', text: 'hello' });
  });

  test('invalid events and EOF without done fail visibly', async () => {
    const badFetch = (line: string) => {
      vi.stubGlobal('fetch', vi.fn(async () => new Response(line, { status: 200 })));
    };
    badFetch('{"type":"token","attempt_id":"a","text":4}\n');
    await expect(streamDocumentSummary('/summary', {}, new AbortController().signal, () => {})).rejects.toThrow();
    badFetch('{"type":"started","attempt_id":"a","revision":"r","section_id":"s","attempt":{}}\n');
    await expect(streamDocumentSummary('/summary', {}, new AbortController().signal, () => {})).rejects.toThrow(/ended before/i);
  });
});
