import directCapture from './fixtures/evidenceSearch/direct.json';
import invalidCapture from './fixtures/evidenceSearch/invalid.json';
import searchCapture from './fixtures/evidenceSearch/search.json';
import { describe, expect, test } from 'vitest';
import { messagesResponseSchema, streamEventSchema } from '../src/api/types';

const captures = [directCapture, searchCapture, invalidCapture];

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('Expected a captured object.');
  }
  return value as Record<string, unknown>;
}

function capturedEvents(capture: unknown): unknown[] {
  const value = asRecord(capture).events;
  if (!Array.isArray(value)) throw new Error('Capture is missing its event list.');
  return value;
}

function capturedSaved(capture: unknown): unknown {
  return asRecord(capture).saved;
}

describe('captured optional evidence-search wire contract', () => {
  test('captured progress, token and terminal events parse without changing their payloads', () => {
    for (const capture of captures) {
      for (const event of capturedEvents(capture)) {
        expect(streamEventSchema.parse(event)).toEqual(event);
      }
    }
  });

  test('captured saved records retain typed version-one metadata and source labels', () => {
    for (const capture of captures) {
      expect(messagesResponseSchema.parse(capturedSaved(capture))).toEqual(capturedSaved(capture));
    }
    const direct = messagesResponseSchema.parse(capturedSaved(directCapture));
    expect(direct.messages[1].retrieval?.evidence_search?.outcome).toBe('direct_answer');
    expect(direct.messages[1].retrieval?.citations[0].source_label).toBe('E1');
  });

  test('nested version-one evidence metadata rejects malformed and unknown fields', () => {
    const saved = asRecord(structuredClone<unknown>(capturedSaved(directCapture)));
    const messages = saved.messages;
    if (!Array.isArray(messages)) throw new Error('Capture is missing saved messages.');
    const assistant = asRecord(messages[1]);
    const retrieval = asRecord(assistant.retrieval);
    const evidenceSearch = asRecord(retrieval.evidence_search);
    evidenceSearch.generation_count = 'one';
    expect(messagesResponseSchema.safeParse(saved).success).toBe(false);

    const withUnknown = asRecord(structuredClone<unknown>(capturedSaved(directCapture)));
    const unknownMessages = withUnknown.messages;
    if (!Array.isArray(unknownMessages)) throw new Error('Capture is missing saved messages.');
    const unknownAssistant = asRecord(unknownMessages[1]);
    const unknownRetrieval = asRecord(unknownAssistant.retrieval);
    asRecord(unknownRetrieval.evidence_search).unrecognized = true;
    expect(messagesResponseSchema.safeParse(withUnknown).success).toBe(false);
  });

  test('old stored records and optional citation labels remain compatible', () => {
    const legacy = {
      messages: [
        {
          role: 'assistant',
          content: 'Legacy answer.',
          retrieval: {
            mode: 'keyword',
            warning: null,
            citations: [
              {
                chunk_id: 'f1:0',
                file_id: 'f1',
                file_name: 'notes.pdf',
                headings: [],
                pages: [],
                bboxes: [],
                assets: [],
                text: 'A legacy source excerpt.',
              },
            ],
            evidence_search: null,
          },
        },
      ],
    };
    expect(messagesResponseSchema.parse(legacy)).toMatchObject(legacy);
    expect(
      streamEventSchema.parse({
        type: 'done',
        model: 'local',
        retrieval: { mode: 'keyword', warning: null, citations: [] },
      }),
    ).toMatchObject({ type: 'done' });
  });

  test('public evidence status accepts only documented stages and safe warning text', () => {
    expect(streamEventSchema.parse({ type: 'evidence_status', stage: 'searching' })).toEqual({
      type: 'evidence_status',
      stage: 'searching',
    });
    expect(
      streamEventSchema.parse({
        type: 'evidence_status',
        stage: 'answering',
        warning: 'No additional passage matched the request.',
      }),
    ).toMatchObject({ type: 'evidence_status', stage: 'answering' });
    expect(streamEventSchema.safeParse({ type: 'evidence_status', stage: 'retrieving' }).success).toBe(false);
  });
});
