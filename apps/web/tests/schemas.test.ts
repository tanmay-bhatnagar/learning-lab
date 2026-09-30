import { describe, expect, test, vi } from 'vitest';
import { api, stream } from '../src/api/client';
import {
  parsePayload,
  settingsSchema,
  streamEventSchema,
  thinkingPrefsSchema,
  topicsResponseSchema,
} from '../src/api/types';

describe('zod schemas', () => {
  test('parsePayload rejects malformed topics response', () => {
    expect(() => parsePayload(topicsResponseSchema, { topics: 'nope' }, '/topics')).toThrow(/Invalid \/topics/);
  });

  test('parsePayload accepts extra keys on loose objects', () => {
    const topic = parsePayload(
      topicsResponseSchema,
      {
        topics: [{ id: 'a', name: 'A', future_field: true }],
      },
      '/topics',
    );
    expect(topic.topics[0].id).toBe('a');
  });

  test('settingsSchema rejects missing fields', () => {
    expect(() => parsePayload(settingsSchema, { model: 'x' }, '/settings')).toThrow(/Invalid \/settings/);
  });

  test('streamEventSchema rejects unknown event type', () => {
    const result = streamEventSchema.safeParse({ type: 'ping' });
    expect(result.success).toBe(false);
  });

  test('thinkingPrefsSchema rejects non-record values', () => {
    expect(thinkingPrefsSchema.safeParse(['bad']).success).toBe(false);
    expect(thinkingPrefsSchema.safeParse({ m1: true, m2: 'high' }).success).toBe(true);
  });
});

describe('api client validation', () => {
  test('api throws on malformed JSON body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('not json', { status: 200, headers: { 'Content-Type': 'application/json' } })),
    );
    await expect(api('/topics', topicsResponseSchema)).rejects.toThrow(/not JSON/);
    vi.unstubAllGlobals();
  });

  test('api throws on schema mismatch', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ topics: null })),
    );
    await expect(api('/topics', topicsResponseSchema)).rejects.toThrow(/Invalid \/topics/);
    vi.unstubAllGlobals();
  });

  test('stream throws on malformed NDJSON line', async () => {
    const encoder = new TextEncoder();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        body: {
          getReader: () => ({
            read: async () => ({ done: true, value: encoder.encode('{"type":"token"') }),
            cancel: async () => {},
            releaseLock: () => {},
          }),
        },
      })),
    );
    await expect(stream('/topics/t/chat', { message: 'hi' }, new AbortController().signal, () => {})).rejects.toThrow(
      /not JSON/,
    );
    vi.unstubAllGlobals();
  });

  test('stream throws on invalid event shape', async () => {
    const encoder = new TextEncoder();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        body: {
          getReader: () => ({
            read: async () => ({ done: true, value: encoder.encode('{"type":"ping"}\n') }),
            cancel: async () => {},
            releaseLock: () => {},
          }),
        },
      })),
    );
    await expect(stream('/topics/t/chat', { message: 'hi' }, new AbortController().signal, () => {})).rejects.toThrow(
      /Invalid stream event/,
    );
    vi.unstubAllGlobals();
  });
});
