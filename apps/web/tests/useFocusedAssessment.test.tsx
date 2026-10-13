import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { readSavedPrerequisites, type PrerequisiteAssessment, type PrerequisiteState } from '../src/api/prerequisites';
import { useFocusedAssessment } from '../src/hooks/useFocusedAssessment';

vi.mock('../src/api/prerequisites', () => ({ readSavedPrerequisites: vi.fn() }));

const revision = 'a'.repeat(64);
const focus = {
  file_id: 'file-a',
  assessment_id: 'assessment-a',
  map_revision: revision,
  section_id: 'section-a',
};
const assessment: PrerequisiteAssessment = {
  attempt_id: 'attempt-a',
  assessment_id: focus.assessment_id,
  topic_id: 'topic-a',
  file_id: focus.file_id,
  map_revision: focus.map_revision,
  section_id: focus.section_id,
  cv_id: 'c'.repeat(32),
  cv_text_sha256: 'b'.repeat(64),
  source_sha256: 'd'.repeat(64),
  overview: 'Review the main concepts.',
  requirements: [
    {
      requirement_id: `req-${'e'.repeat(24)}`,
      concept: 'Basic Python',
      reason: 'Used in the examples.',
      question: 'Are you already comfortable with Basic Python?',
      source_labels: ['S1'],
      cv_background: 'not_stated',
      cv_source_labels: [],
      cv_quote: '',
      comfort: null,
      comfort_status: 'pending',
    },
  ],
  sources: [{ label: 'S1', unit_id: 'unit-a', source_refs: ['doc:section-a'], pages: [1] }],
  finished_at: '2026-10-13T10:01:00Z',
};
const savedState: PrerequisiteState = {
  schema_version: 1,
  topic_id: 'topic-a',
  file_id: 'file-a',
  map_revision: revision,
  selected_cv: null,
  attempts: [],
  assessments: [assessment],
  current_assessment: null,
};

describe('useFocusedAssessment', () => {
  test('reloads the exact historical completed assessment from the active conversation focus without a map fallback', async () => {
    vi.mocked(readSavedPrerequisites).mockResolvedValue(savedState);
    const { result } = renderHook(() => useFocusedAssessment('topic-a', focus, null));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(readSavedPrerequisites).toHaveBeenCalledWith('topic-a', 'file-a', 'assessment-a', expect.any(AbortSignal));
    expect(result.current.assessment).toEqual(assessment);
  });

  test('rejects history that does not match the full saved assessment identity', async () => {
    vi.mocked(readSavedPrerequisites).mockResolvedValue({ ...savedState, assessments: [] });
    const { result } = renderHook(() => useFocusedAssessment('topic-a', focus, null));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.assessment).toBeNull();
    expect(result.current.error).toMatch(/no longer available/i);
  });

  test('uses only the explicit map fallback when the conversation has no active focus', () => {
    vi.mocked(readSavedPrerequisites).mockClear();
    const { result } = renderHook(() => useFocusedAssessment('topic-a', null, assessment));

    expect(result.current.assessment).toEqual(assessment);
    expect(readSavedPrerequisites).not.toHaveBeenCalled();
  });

  test('reloads after the user asks to retry a missing saved assessment', async () => {
    vi.mocked(readSavedPrerequisites).mockResolvedValue({ ...savedState, assessments: [] });
    const { result } = renderHook(() => useFocusedAssessment('topic-a', focus, null));
    await waitFor(() => expect(result.current.error).not.toBe(''));
    vi.mocked(readSavedPrerequisites).mockResolvedValue(savedState);

    await act(async () => result.current.reload());

    await waitFor(() => expect(result.current.assessment).toEqual(assessment));
  });
});
