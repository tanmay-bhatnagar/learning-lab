import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import {
  readPrerequisites,
  streamPrerequisites,
  type PrerequisiteAssessment,
  type PrerequisiteState,
} from '../src/api/prerequisites';
import { usePrerequisites } from '../src/hooks/usePrerequisites';

vi.mock('../src/api/prerequisites', () => ({
  readPrerequisites: vi.fn(),
  streamPrerequisites: vi.fn(),
}));

const revision = 'a'.repeat(64);
const cvId = 'c'.repeat(32);
const completedAttempt = {
  id: 'attempt-1',
  assessment_id: 'assessment-1',
  topic_id: 'topic-a',
  file_id: 'file-a',
  map_revision: revision,
  section_id: 'section-a',
  status: 'completed' as const,
  started_at: '2026-10-13T10:00:00Z',
  finished_at: '2026-10-13T10:01:00Z',
  provenance: {
    prompt_version: 'section-prerequisites-v2',
    source_sha256: revision,
    runtime_policy_sha256: revision,
    cv_id: cvId,
    cv_text_sha256: revision,
    goal: 'Understand this section',
    model: 'local-model',
  },
  diagnostic: null,
};
const assessment: PrerequisiteAssessment = {
  attempt_id: completedAttempt.id,
  assessment_id: completedAttempt.assessment_id,
  topic_id: completedAttempt.topic_id,
  file_id: completedAttempt.file_id,
  map_revision: revision,
  section_id: completedAttempt.section_id,
  cv_id: cvId,
  cv_text_sha256: revision,
  source_sha256: revision,
  overview: 'A high-level outline of the prerequisites for this section.',
  requirements: [
    {
      requirement_id: `req-${'b'.repeat(24)}`,
      concept: 'Basic Python',
      reason: 'The section uses short programs to explain its method.',
      question: 'Are you already comfortable with Basic Python?',
      source_labels: ['S1'],
      cv_background: 'not_stated',
      cv_source_labels: [],
      cv_quote: '',
      comfort: null,
      comfort_status: 'pending',
    },
  ],
  sources: [{ label: 'S1', unit_id: 'unit-1', source_refs: ['doc:section-a'], pages: [2] }],
  finished_at: completedAttempt.finished_at,
};

function state(current: PrerequisiteAssessment | null, hasCv = true): PrerequisiteState {
  return {
    schema_version: 1,
    topic_id: 'topic-a',
    file_id: 'file-a',
    map_revision: revision,
    selected_cv: hasCv ? { id: cvId, original_name: 'CV.pdf', extracted_sha256: revision } : null,
    attempts: current ? [completedAttempt] : [],
    assessments: current ? [current] : [],
    current_assessment: current,
  };
}

const options = {
  topicId: 'topic-a',
  fileId: 'file-a',
  sectionId: 'section-a',
  mapRevision: revision,
  mapReady: true,
  activeCvId: cvId,
  activeCvHash: revision,
  modelId: 'local-model',
  contextLimit: 8192,
  think: false,
  defaultGoal: 'Understand this section',
  activity: 'idle' as const,
  activityApi: { begin: vi.fn(() => true), end: vi.fn() },
  refreshProficiency: vi.fn(async () => undefined),
};

describe('usePrerequisites', () => {
  afterEach(() => vi.resetAllMocks());

  test('loads matching saved assessment and never starts generation without the selected CV', async () => {
    vi.mocked(readPrerequisites).mockResolvedValue(state(null, false));
    const { result } = renderHook(() => usePrerequisites(options));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => result.current.generate());

    expect(readPrerequisites).toHaveBeenCalledWith('topic-a', 'file-a', 'section-a', expect.any(AbortSignal));
    expect(result.current.blockedReason).toMatch(/CV/i);
    expect(streamPrerequisites).not.toHaveBeenCalled();
  });

  test('sends the captured section/model/goal and adopts only the reloaded completed assessment', async () => {
    vi.mocked(readPrerequisites).mockResolvedValueOnce(state(null)).mockResolvedValueOnce(state(assessment));
    vi.mocked(streamPrerequisites).mockImplementation(async (_topic, _file, _section, _input, _signal, onEvent) => {
      onEvent({ type: 'progress', attempt_id: completedAttempt.id, phase: 'generating' });
      onEvent({
        type: 'done',
        attempt_id: completedAttempt.id,
        assessment,
        proficiency_revision: 3,
        attempt: completedAttempt,
      });
    });
    const activityApi = { begin: vi.fn(() => true), end: vi.fn() };
    const { result } = renderHook(() => usePrerequisites({ ...options, activityApi }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => result.current.generate());

    expect(streamPrerequisites).toHaveBeenCalledWith(
      'topic-a',
      'file-a',
      'section-a',
      { revision, model: 'local-model', context_limit: 8192, think: false, goal: 'Understand this section' },
      expect.any(AbortSignal),
      expect.any(Function),
    );
    expect(result.current.assessment).toEqual(assessment);
    expect(result.current.assessment?.requirements[0].comfort).toBeNull();
    expect(result.current.progress).not.toMatch(/Basic Python|model output/i);
    expect(activityApi.begin).toHaveBeenCalledWith('generatePrerequisites');
    expect(activityApi.end).toHaveBeenCalledOnce();
  });

  test('preserves the prior completed assessment when regeneration fails', async () => {
    vi.mocked(readPrerequisites).mockResolvedValue(state(assessment));
    vi.mocked(streamPrerequisites).mockRejectedValue(new Error('local model unavailable'));
    const { result } = renderHook(() => usePrerequisites(options));
    await waitFor(() => expect(result.current.assessment).toEqual(assessment));

    await act(async () => result.current.generate());

    expect(result.current.assessment).toEqual(assessment);
    expect(result.current.error).toMatch(/local model unavailable/i);
  });

  test('keeps an older completed result visible and labels it when the selected CV changes', async () => {
    vi.mocked(readPrerequisites).mockResolvedValue(state(assessment, false));
    const { result } = renderHook(() => usePrerequisites({ ...options, activeCvId: null, activeCvHash: null }));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.assessment).toEqual(assessment);
    expect(result.current.assessmentStaleReason).toMatch(/different CV/i);
  });

  test('does not reload saved state after an in-flight generation unmounts', async () => {
    vi.mocked(readPrerequisites).mockResolvedValue(state(null));
    vi.mocked(streamPrerequisites).mockImplementation(
      async (_topic, _file, _section, _input, signal) =>
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
        }),
    );
    const activityApi = { begin: vi.fn(() => true), end: vi.fn() };
    const { result, unmount } = renderHook(() => usePrerequisites({ ...options, activityApi }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    let generation: Promise<void> | undefined;
    act(() => {
      generation = result.current.generate();
    });
    await waitFor(() => expect(streamPrerequisites).toHaveBeenCalledOnce());
    unmount();
    await act(async () => generation);

    expect(readPrerequisites).toHaveBeenCalledOnce();
    expect(activityApi.end).toHaveBeenCalledOnce();
  });

  test('explicit Stop aborts generation and reloads durable saved state', async () => {
    vi.mocked(readPrerequisites).mockResolvedValue(state(null));
    vi.mocked(streamPrerequisites).mockImplementation(
      async (_topic, _file, _section, _input, signal) =>
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
        }),
    );
    const activityApi = { begin: vi.fn(() => true), end: vi.fn() };
    const { result } = renderHook(() => usePrerequisites({ ...options, activityApi }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    let generation: Promise<void> | undefined;
    act(() => {
      generation = result.current.generate();
    });
    await waitFor(() => expect(streamPrerequisites).toHaveBeenCalledOnce());
    await act(async () => result.current.stop());
    await act(async () => generation);

    expect(readPrerequisites).toHaveBeenCalledTimes(2);
    expect(activityApi.end).toHaveBeenCalledOnce();
  });
});
