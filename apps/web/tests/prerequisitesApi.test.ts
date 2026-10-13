import { afterEach, describe, expect, test, vi } from 'vitest';
import {
  importPrerequisites,
  prerequisiteAssessmentSchema,
  prerequisiteStateSchema,
  prerequisiteStreamEventSchema,
  readPrerequisites,
  streamPrerequisites,
} from '../src/api/prerequisites';
import { messageSchema } from '../src/api/types';

const sha = 'a'.repeat(64);
const source = { label: 'S1', unit_id: 'unit-1', source_refs: ['doc:section-1'], pages: [2] };
const requirement = {
  requirement_id: `req-${'b'.repeat(24)}`,
  concept: 'Basic Python',
  reason: 'The section uses short programs to explain the method.',
  question: 'Are you already comfortable with Basic Python?',
  source_labels: ['S1'],
  cv_background: 'not_stated',
  cv_source_labels: [],
  cv_quote: '',
  comfort: null,
  comfort_status: 'pending',
};
const attempt = {
  id: 'attempt-1',
  assessment_id: 'assessment-1',
  topic_id: 'topic-a',
  file_id: 'file-a',
  map_revision: sha,
  section_id: 'section-a',
  status: 'completed',
  started_at: '2026-10-13T10:00:00Z',
  finished_at: '2026-10-13T10:01:00Z',
  provenance: {
    prompt_version: 'section-prerequisites-v2',
    source_sha256: sha,
    runtime_policy_sha256: sha,
    cv_id: 'c'.repeat(32),
    cv_text_sha256: sha,
    goal: 'Learn the paper methods.',
    model: 'qwen-local',
  },
  diagnostic: null,
};
const assessment = {
  attempt_id: attempt.id,
  assessment_id: attempt.assessment_id,
  topic_id: attempt.topic_id,
  file_id: attempt.file_id,
  map_revision: attempt.map_revision,
  section_id: attempt.section_id,
  cv_id: attempt.provenance.cv_id,
  cv_text_sha256: sha,
  source_sha256: sha,
  overview: 'A brief conceptual orientation before reading this section.',
  requirements: [requirement],
  sources: [source],
  finished_at: attempt.finished_at,
};
const emptyState = {
  schema_version: 1,
  topic_id: 'topic-a',
  file_id: 'file-a',
  map_revision: null,
  selected_cv: null,
  attempts: [],
  assessments: [],
  current_assessment: null,
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function streamResponse(lines: object[]) {
  const bytes = new TextEncoder().encode(lines.map((line) => JSON.stringify(line)).join('\n') + '\n');
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(bytes.slice(0, 19));
        controller.enqueue(bytes.slice(19));
        controller.close();
      },
    }),
    { headers: { 'Content-Type': 'application/x-ndjson' } },
  );
}

afterEach(() => vi.unstubAllGlobals());

describe('prerequisite API contracts', () => {
  test('accepts absent map/CV and no saved attempts as an explicit empty state', () => {
    expect(prerequisiteStateSchema.parse(emptyState)).toEqual(emptyState);
    expect(
      prerequisiteStateSchema.parse({
        ...emptyState,
        map_revision: sha,
        selected_cv: { id: 'c'.repeat(32), original_name: 'Resume.pdf', extracted_sha256: sha },
        attempts: [attempt],
        assessments: [assessment],
        current_assessment: assessment,
      }).current_assessment?.assessment_id,
    ).toBe('assessment-1');
  });

  test('keeps generated questions pending and does not accept a generated comfort answer', () => {
    expect(prerequisiteAssessmentSchema.parse(assessment).requirements[0]).toMatchObject({
      question: 'Are you already comfortable with Basic Python?',
      comfort: null,
      comfort_status: 'pending',
    });
    expect(
      prerequisiteAssessmentSchema.safeParse({
        ...assessment,
        requirements: [{ ...requirement, comfort: 'comfortable' }],
      }).success,
    ).toBe(false);
    expect(
      prerequisiteAssessmentSchema.safeParse({
        ...assessment,
        requirements: [{ ...requirement, cv_background: 'mentioned', cv_source_labels: [], cv_quote: '' }],
      }).success,
    ).toBe(false);
  });

  test('reads the optional section-filtered state using encoded path segments', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(emptyState));
    vi.stubGlobal('fetch', fetchMock);
    await readPrerequisites('topic/one', 'file one', 'section/one');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/topics/topic%2Fone/files/file%20one/prerequisites?section_id=section%2Fone',
      {},
    );
  });

  test('streams started, progress and validated terminal assessment without exposing raw model tokens', async () => {
    const generatingAttempt = { ...attempt, status: 'generating', finished_at: null };
    const completedAttempt = attempt;
    const events = [
      {
        type: 'started',
        attempt_id: attempt.id,
        revision: sha,
        section_id: attempt.section_id,
        attempt: generatingAttempt,
      },
      { type: 'progress', attempt_id: attempt.id, phase: 'generating' },
      { type: 'done', attempt_id: attempt.id, assessment, proficiency_revision: 9, attempt: completedAttempt },
    ];
    const fetchMock = vi.fn().mockResolvedValue(streamResponse(events));
    vi.stubGlobal('fetch', fetchMock);
    const received: unknown[] = [];
    await streamPrerequisites(
      'topic-a',
      'file-a',
      'section-a',
      { revision: sha, model: 'qwen-local', context_limit: 8192, think: false, goal: 'Read critically' },
      new AbortController().signal,
      (event) => received.push(event),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/topics/topic-a/files/file-a/map/sections/section-a/prerequisites',
      expect.objectContaining({ method: 'POST', headers: { 'Content-Type': 'application/json' } }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      revision: sha,
      model: 'qwen-local',
      context_limit: 8192,
      think: false,
      goal: 'Read critically',
    });
    expect(received.map((event) => (event as { type: string }).type)).toEqual(['started', 'progress', 'done']);
    expect(
      prerequisiteStreamEventSchema.safeParse({ type: 'token', attempt_id: attempt.id, text: 'raw model output' })
        .success,
    ).toBe(false);
    expect(
      prerequisiteStreamEventSchema.safeParse({ type: 'thinking', attempt_id: attempt.id, text: 'private chain' })
        .success,
    ).toBe(false);
  });

  test('rejects malformed streams and EOF before a terminal event', async () => {
    const malformed = streamResponse([{ type: 'token', attempt_id: attempt.id, text: 'raw answer' }]);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(malformed));
    await expect(
      streamPrerequisites(
        'topic-a',
        'file-a',
        'section-a',
        { revision: sha, model: 'qwen-local' },
        new AbortController().signal,
        () => undefined,
      ),
    ).rejects.toThrow();

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        streamResponse([
          {
            type: 'started',
            attempt_id: attempt.id,
            revision: sha,
            section_id: attempt.section_id,
            attempt: { ...attempt, status: 'generating', finished_at: null },
          },
          { type: 'progress', attempt_id: attempt.id, phase: 'generating' },
        ]),
      ),
    );
    await expect(
      streamPrerequisites(
        'topic-a',
        'file-a',
        'section-a',
        { revision: sha, model: 'qwen-local' },
        new AbortController().signal,
        () => undefined,
      ),
    ).rejects.toThrow(/ended before/i);
  });

  test('delivers a terminal generation error without exposing its failed attempt as an assessment', async () => {
    const failedAttempt = {
      ...attempt,
      status: 'error',
      diagnostic: 'The local model could not complete prerequisite generation.',
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        streamResponse([
          {
            type: 'started',
            attempt_id: attempt.id,
            revision: sha,
            section_id: attempt.section_id,
            attempt: { ...attempt, status: 'generating', finished_at: null },
          },
          { type: 'error', attempt_id: attempt.id, message: failedAttempt.diagnostic, attempt: failedAttempt },
        ]),
      ),
    );
    const received: unknown[] = [];
    await streamPrerequisites(
      'topic-a',
      'file-a',
      'section-a',
      { revision: sha, model: 'qwen-local' },
      new AbortController().signal,
      (event) => received.push(event),
    );
    expect(received.map((event) => (event as { type: string }).type)).toEqual(['started', 'error']);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        streamResponse([
          {
            type: 'started',
            attempt_id: attempt.id,
            revision: sha,
            section_id: attempt.section_id,
            attempt: { ...attempt, status: 'generating', finished_at: null },
          },
          {
            type: 'done',
            attempt_id: attempt.id,
            assessment,
            proficiency_revision: 9,
            attempt: { ...attempt, assessment_id: 'another-assessment' },
          },
        ]),
      ),
    );
    await expect(
      streamPrerequisites(
        'topic-a',
        'file-a',
        'section-a',
        { revision: sha, model: 'qwen-local' },
        new AbortController().signal,
        () => undefined,
      ),
    ).rejects.toThrow(/does not match its assessment attempt/i);
  });

  test('validates imported snapshots and exact destination/assessment identities', async () => {
    const importedMessage = {
      role: 'user',
      content:
        'Saved prerequisites — Results\nSuggestions are model-inferred, not verified prerequisites or proof of mastery.',
      prerequisite_import: {
        schema_version: 1,
        import_id: 'd'.repeat(64),
        conversation_id: 'conversation-a',
        topic_id: 'topic-a',
        file_id: 'file-a',
        assessment_id: 'assessment-1',
        map_revision: sha,
        section_id: 'section-a',
        section_title: 'Results',
        goal: 'Learn the paper methods.',
        model: 'qwen-local',
        assessment_finished_at: '2026-10-13T10:01:00Z',
        imported_at: '2026-10-13T10:02:00Z',
        sources: [source],
        content_sha256: sha,
      },
    };
    expect(messageSchema.safeParse(importedMessage).success).toBe(true);
    expect(
      messageSchema.safeParse({
        ...importedMessage,
        prerequisite_import: { ...importedMessage.prerequisite_import, schema_version: 2 },
      }).success,
    ).toBe(false);
    const learnerContext = { schema_version: 1, revision: 4, include_cv: false, active_assessment: null };
    const response = {
      conversation_id: 'conversation-a',
      imported: true,
      message: importedMessage,
      messages: [importedMessage],
      learner_context: learnerContext,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(response));
    vi.stubGlobal('fetch', fetchMock);
    await importPrerequisites('topic-a', 'conversation-a', {
      file_id: 'file-a',
      assessment_id: 'assessment-1',
      revision: sha,
      section_id: 'section-a',
      expected_revision: 4,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/topics/topic-a/conversations/conversation-a/prerequisite-imports',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      file_id: 'file-a',
      assessment_id: 'assessment-1',
      revision: sha,
      section_id: 'section-a',
      expected_revision: 4,
    });
  });
});

test.each([undefined, 'interrupted'])(
  'accepts a non-actionable uncertainty error with attempt status %s',
  async (status) => {
    const error = {
      type: 'error',
      attempt_id: attempt.id,
      message: 'Could not verify whether prerequisites were saved.',
      ...(status ? { attempt: { ...attempt, status, diagnostic: 'Interrupted' } } : {}),
    };
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          streamResponse([
            {
              type: 'started',
              attempt_id: attempt.id,
              revision: sha,
              section_id: attempt.section_id,
              attempt: { ...attempt, status: 'generating', finished_at: null },
            },
            error,
          ]),
        ),
    );
    const received: unknown[] = [];
    await streamPrerequisites(
      'topic-a',
      'file-a',
      'section-a',
      { revision: sha, model: 'qwen-local' },
      new AbortController().signal,
      (event) => received.push(event),
    );
    expect(received).toEqual([expect.objectContaining({ type: 'started' }), error]);
    expect(received.some((event) => (event as { type: string }).type === 'done')).toBe(false);
  },
);
