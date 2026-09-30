import { describe, expect, test } from 'vitest';
import {
  filesResponseSchema,
  messagesResponseSchema,
  modelsResponseSchema,
  parsePayload,
  streamEventSchema,
  topicsResponseSchema,
} from '../src/api/types';

// Captured from a live backend on synthetic fixtures; Python writes absent values as null.
const doclingFile = {
  id: 'e30beb08e7db4f3dacf23565bd38aef5',
  name: 'fixture.pdf',
  original_name: '2026_09_30_fixture-e30beb08e7db4f3dacf23565bd38aef5.pdf',
  status: 'ready',
  parser: 'docling',
  markdown_name: '2026_09_30_fixture-e30beb08e7db4f3dacf23565bd38aef5.md',
  docling_name: '2026_09_30_fixture-e30beb08e7db4f3dacf23565bd38aef5.docling.json',
  chunks_name: '2026_09_30_fixture-e30beb08e7db4f3dacf23565bd38aef5.chunks.jsonl',
  parse_name: '2026_09_30_fixture-e30beb08e7db4f3dacf23565bd38aef5.parse.json',
  content_sha256: '40ef15b5e6658c3d132fd3288039a81056dc5e70c4c0796b038dbbe664982902',
  parser_version: '2.127.0',
  page_count: 1,
  asset_count: 0,
  assets: [
    {
      id: 'page_000001',
      name: '2026_09_30_fixture-e30beb08e7db4f3dacf23565bd38aef5.page_000001.png',
      kind: 'page',
      page: 1,
      bbox: null,
      caption: null,
      doc_ref: null,
    },
  ],
  warnings: [],
  extraction_diagnostics: {
    status: 'unassessed',
    note: 'Docling reported no extraction issues; fidelity remains unassessed.',
    findings: [],
  },
  index_status: 'ready',
  index_mode: 'hybrid',
  embedding_model: 'nomic-embed-text',
};

const doneEvent = {
  type: 'done',
  context: { used: 155, limit: 16384, estimated: false, truncated_messages: 0 },
  model: 'qwen3.5:4b-q8_0',
  retrieval: { mode: 'none', warning: null, citations: [] },
};

const savedReply = {
  role: 'assistant',
  content: 'Hello again!',
  thinking: '',
  model: 'qwen3.5:4b-q8_0',
  retrieval: { mode: 'none', warning: null, citations: [] },
};

const legacyCitation = {
  chunk_id: 'f1:0',
  file_id: 'f1',
  file_name: 'notes.pdf',
  headings: [],
  pages: [],
  bboxes: [],
  assets: [],
  trace: {},
  text: 'The answer is 42.',
};

describe('real backend payloads', () => {
  test('a Docling file record with null asset fields parses unchanged', () => {
    const parsed = parsePayload(filesResponseSchema, { files: [doclingFile] }, '/files');
    expect(parsed).toEqual({ files: [doclingFile] });
  });

  test('a chat done event with a null retrieval warning parses unchanged', () => {
    expect(streamEventSchema.parse(doneEvent)).toEqual(doneEvent);
  });

  test('saved replies with a null warning and a legacy empty trace parse unchanged', () => {
    const body = {
      messages: [
        { role: 'user', content: 'hi', file_ids: [] },
        savedReply,
        { ...savedReply, retrieval: { mode: 'keyword', warning: null, citations: [legacyCitation] } },
      ],
      context: { used: 155, limit: 16384, estimated: false, truncated_messages: 0 },
    };
    expect(parsePayload(messagesResponseSchema, body, '/messages')).toEqual(body);
  });

  test('null optional fields on topics and models parse', () => {
    expect(topicsResponseSchema.safeParse({ topics: [{ id: 't', name: 'T', learning_goal: null }] }).success).toBe(
      true,
    );
    const models = {
      models: [{ id: 'm', name: 'm', display_name: null, quantization: null, thinking: { type: 'none' } }],
      error: null,
    };
    expect(modelsResponseSchema.safeParse(models).success).toBe(true);
  });
});
