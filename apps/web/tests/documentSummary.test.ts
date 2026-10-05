import { afterEach, describe, expect, test, vi } from 'vitest';
import contract from './fixtures/document-summary-import-contract.json';
import {
  savedSummarySchema,
  summaryImportResponseSchema,
  streamDocumentSummary,
  type SummaryStreamEvent,
} from '../src/api/documentMap';
import { foldSummaryEvent, sectionSummaryState } from '../src/state/documentMap';
import mapFixture from './fixtures/documentMapApi.json';

afterEach(() => vi.unstubAllGlobals());

describe('document summary wire contract', () => {
  test('accepts actual saved-summary and import payloads captured from the backend', () => {
    expect(savedSummarySchema.parse(contract.summary).content).toContain('[S1]');
    expect(summaryImportResponseSchema.parse(contract.import).imported).toBe(true);
  });

  test('dedicated decoder handles chunk boundaries and preserves event identity', async () => {
    const [started, , token, done] = contract.summary_events;
    const chunks = [`${JSON.stringify(started)}\n`, `${JSON.stringify(token)}\n${JSON.stringify(done)}\n`];
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
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
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => new Response(line, { status: 200 })),
      );
    };
    badFetch(`${JSON.stringify({ ...contract.summary_events[0], type: 'token', text: 4 })}\n`);
    await expect(streamDocumentSummary('/summary', {}, new AbortController().signal, () => {})).rejects.toThrow();
    badFetch(`${JSON.stringify(contract.summary_events[0])}\n`);
    await expect(streamDocumentSummary('/summary', {}, new AbortController().signal, () => {})).rejects.toThrow(
      /ended before/i,
    );
  });

  test('a terminal event suppresses later events in the same network chunk', async () => {
    const started = contract.summary_events[0];
    const done = contract.summary_events[3];
    const error = {
      type: 'error' as const,
      attempt_id: started.attempt_id,
      message: 'synthetic error',
      attempt: {
        ...started.attempt,
        status: 'error',
        finished_at: '2026-10-05T00:00:01Z',
        error: 'synthetic error',
      },
    };
    const cases = [
      [started, error, done],
      [started, done, contract.summary_events[2]],
    ];
    for (const sequence of cases) {
      vi.stubGlobal(
        'fetch',
        vi.fn(
          async () => new Response(`${sequence.map((event) => JSON.stringify(event)).join('\n')}\n`, { status: 200 }),
        ),
      );
      const received: SummaryStreamEvent[] = [];
      await streamDocumentSummary('/summary', {}, new AbortController().signal, (event) => received.push(event));
      expect(received.map((event) => event.type)).toEqual(
        sequence
          .slice(0, sequence.findIndex((event) => event.type === 'done' || event.type === 'error') + 1)
          .map((event) => event.type),
      );
    }
  });

  test('pure event reducer rejects other scopes and keeps prior success when regeneration fails', () => {
    const [started, , token, done, error] = [
      contract.summary_events[0],
      contract.summary_events[1],
      contract.summary_events[2],
      contract.summary_events[3],
      {
        type: 'error' as const,
        attempt_id: contract.summary_events[0].attempt_id,
        message: 'synthetic regeneration failed',
        attempt: {
          ...contract.summary_events[0].attempt,
          status: 'error',
          finished_at: '2026-10-05T00:00:00Z',
          error: 'synthetic regeneration failed',
        },
      },
    ];
    const section = { ...mapFixture.build_response.map.sections[0], id: contract.summary.section_id };
    const savedSummary = savedSummarySchema.parse(contract.summary);
    const scope = {
      topic: 'topic-a',
      fileId: 'synthetic-paper',
      revision: savedSummary.revision,
      sectionId: section.id,
    };
    const initial = sectionSummaryState(scope, { ...section, last_summary: savedSummary });
    const generated = foldSummaryEvent(initial, started as SummaryStreamEvent, scope);
    const withToken = foldSummaryEvent(generated, token as SummaryStreamEvent, scope);
    const wrongScope = foldSummaryEvent(withToken, token as SummaryStreamEvent, { ...scope, fileId: 'other' });
    const failed = foldSummaryEvent(wrongScope, error as SummaryStreamEvent, scope);

    expect(wrongScope).toBe(withToken);
    expect(failed.summary?.content).toBe(contract.summary.content);
    expect(failed.attempt?.status).toBe('error');
    expect(failed.content).toBe('A synthetic statement [S1].');
    expect(failed.error).toBe('synthetic regeneration failed');
    expect(done.type).toBe('done');
  });

  test('reducer rejects terminal and started attempt records that disagree with the active scope', () => {
    const started = contract.summary_events[0] as Extract<SummaryStreamEvent, { type: 'started' }>;
    const done = contract.summary_events[3] as Extract<SummaryStreamEvent, { type: 'done' }>;
    const section = { ...mapFixture.build_response.map.sections[0], id: contract.summary.section_id };
    const savedSummary = savedSummarySchema.parse(contract.summary);
    const scope = {
      topic: 'topic-a',
      fileId: 'synthetic-paper',
      revision: savedSummary.revision,
      sectionId: section.id,
    };
    const initial = sectionSummaryState(scope, section);
    const invalidStart = {
      ...started,
      attempt: { ...started.attempt, status: 'completed' as const },
    } as SummaryStreamEvent;
    expect(foldSummaryEvent(initial, invalidStart, scope)).toBe(initial);

    const active = foldSummaryEvent(initial, started, scope);
    const invalidDone = {
      ...done,
      attempt: { ...done.attempt, revision: 'b'.repeat(64), section_id: 'other-section' },
    } as SummaryStreamEvent;
    expect(foldSummaryEvent(active, invalidDone, scope)).toBe(active);

    const invalidError = {
      type: 'error' as const,
      attempt_id: started.attempt_id,
      message: 'synthetic failure',
      attempt: {
        ...started.attempt,
        status: 'error' as const,
        revision: 'b'.repeat(64),
        section_id: 'other-section',
      },
    } as SummaryStreamEvent;
    expect(foldSummaryEvent(active, invalidError, scope)).toBe(active);
  });

  test('restores failed attempt text separately from a prior saved summary', () => {
    const section = { ...mapFixture.build_response.map.sections[0], id: contract.summary.section_id };
    const savedSummary = savedSummarySchema.parse(contract.summary);
    const scope = {
      topic: 'topic-a',
      fileId: 'synthetic-paper',
      revision: savedSummary.revision,
      sectionId: section.id,
    };
    const failedAttempt = {
      ...(contract.summary_events[0] as Extract<SummaryStreamEvent, { type: 'started' }>).attempt,
      status: 'error' as const,
      content: 'partial generated text',
      finished_at: '2026-10-05T07:53:00Z',
      error: 'synthetic failure',
    };
    const withPrior = sectionSummaryState(scope, {
      ...section,
      latest_attempt: failedAttempt,
      last_summary: savedSummary,
    });
    const withoutPrior = sectionSummaryState(scope, { ...section, latest_attempt: failedAttempt });
    expect(withPrior.summary?.content).toBe(savedSummary.content);
    expect(withPrior.content).toBe('partial generated text');
    expect(withoutPrior.summary).toBeNull();
    expect(withoutPrior.content).toBe('partial generated text');
  });
});
