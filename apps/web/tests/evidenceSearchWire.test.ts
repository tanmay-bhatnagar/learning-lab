import directCapture from './fixtures/evidenceSearch/direct.json';
import invalidCapture from './fixtures/evidenceSearch/invalid.json';
import searchCapture from './fixtures/evidenceSearch/search.json';
import { describe, expect, test } from 'vitest';
import { messagesResponseSchema, streamEventSchema } from '../src/api/types';

const captures = [directCapture, searchCapture, invalidCapture];

describe('captured optional evidence-search wire contract', () => {
  test('captured progress, token and terminal events parse without changing their payloads', () => {
    for (const capture of captures) {
      for (const event of capture.events) {
        expect(streamEventSchema.parse(event)).toEqual(event);
      }
    }
  });

  test('captured saved records retain typed version-one metadata and source labels', () => {
    for (const capture of captures) {
      expect(messagesResponseSchema.parse(capture.saved)).toEqual(capture.saved);
    }
    const direct = messagesResponseSchema.parse(directCapture.saved);
    expect(direct.messages[1].retrieval?.evidence_search?.outcome).toBe('direct_answer');
    expect(direct.messages[1].retrieval?.citations[0].source_label).toBe('E1');
  });

  test('nested version-one evidence metadata rejects malformed and unknown fields', () => {
    const saved = structuredClone(directCapture.saved);
    const assistant = saved.messages[1];
    assistant.retrieval.evidence_search.generation_count = 'one';
    expect(messagesResponseSchema.safeParse(saved).success).toBe(false);

    const withUnknown = structuredClone(directCapture.saved);
    withUnknown.messages[1].retrieval.evidence_search.unrecognized = true;
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
    expect(messagesResponseSchema.parse(legacy)).toEqual(legacy);
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
