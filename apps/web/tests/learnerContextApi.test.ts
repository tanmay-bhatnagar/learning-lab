import { afterEach, describe, expect, test, vi } from 'vitest';
import { getLearnerContext, learnerContextSchema, updateLearnerContext } from '../src/api/learnerContext';

const empty = { schema_version: 1, revision: 0, include_cv: false, active_assessment: null };
const active = {
  schema_version: 1,
  revision: 2,
  include_cv: true,
  active_assessment: {
    file_id: 'file-a',
    assessment_id: 'assessment-a',
    map_revision: 'a'.repeat(64),
    section_id: 'section-a',
    goal: 'Understand the algorithm.',
  },
};

const jsonResponse = (body: unknown) =>
  new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });

afterEach(() => vi.unstubAllGlobals());

describe('conversation learner-context API', () => {
  test('reads the per-conversation default with null active assessment', () => {
    expect(learnerContextSchema.parse(empty)).toEqual(empty);
  });

  test('parses server-owned active assessment metadata and rejects unknown fields', () => {
    expect(learnerContextSchema.parse(active)).toEqual(active);
    expect(learnerContextSchema.safeParse({ ...active, unsupported: true }).success).toBe(false);
    expect(
      learnerContextSchema.safeParse({
        ...active,
        active_assessment: { ...active.active_assessment, map_revision: 'stale' },
      }).success,
    ).toBe(false);
  });

  test('GET and PATCH paths encode topic and conversation IDs', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(empty)).mockResolvedValueOnce(jsonResponse(active));
    vi.stubGlobal('fetch', fetchMock);
    await getLearnerContext('topic/a', 'conversation one');
    await updateLearnerContext('topic/a', 'conversation one', { expected_revision: 1, include_cv: true });
    expect(fetchMock.mock.calls[0]).toEqual([
      '/api/topics/topic%2Fa/conversations/conversation%20one/learner-context',
      {},
    ]);
    expect(fetchMock.mock.calls[1][0]).toBe('/api/topics/topic%2Fa/conversations/conversation%20one/learner-context');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'PATCH' });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toEqual({ expected_revision: 1, include_cv: true });
  });

  test('allows an explicit disable request without requiring a selected CV', async () => {
    const disabled = { ...empty, revision: 3 };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(disabled));
    vi.stubGlobal('fetch', fetchMock);
    await updateLearnerContext('topic-a', 'conversation-a', { expected_revision: 2, include_cv: false });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      expected_revision: 2,
      include_cv: false,
    });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).not.toHaveProperty('active_assessment');
  });

  test('rejects a server response whose revision does not match the expected atomic update', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...empty, revision: 8, include_cv: true }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(
      updateLearnerContext('topic-a', 'conversation-a', { expected_revision: 2, include_cv: true }),
    ).rejects.toThrow(/unexpected learner-context revision/i);
  });
});
