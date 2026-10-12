import { renderHook, waitFor, act } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { getLearnerContext, updateLearnerContext } from '../src/api/learnerContext';
import { useLearnerContext } from '../src/hooks/useLearnerContext';

vi.mock('../src/api/learnerContext', () => ({
  getLearnerContext: vi.fn(),
  updateLearnerContext: vi.fn(),
}));

const apiState = (revision: number, include_cv: boolean) => ({
  schema_version: 1 as const,
  revision,
  include_cv,
  active_assessment: null,
});

describe('useLearnerContext', () => {
  afterEach(() => vi.resetAllMocks());

  test('loads the selected conversation preference and saves only the requested flag at its current revision', async () => {
    vi.mocked(getLearnerContext).mockResolvedValue(apiState(4, false));
    vi.mocked(updateLearnerContext).mockResolvedValue(apiState(5, true));
    const activityApi = { begin: vi.fn(() => true), end: vi.fn() };
    const { result } = renderHook(() =>
      useLearnerContext({ topicId: 'topic-a', conversationId: 'conversation-a', activity: 'idle', activityApi }),
    );

    await waitFor(() => expect(result.current.preference?.revision).toBe(4));
    await act(async () => result.current.setIncludeCv(true));

    expect(getLearnerContext).toHaveBeenCalledWith('topic-a', 'conversation-a', expect.any(AbortSignal));
    expect(activityApi.begin).toHaveBeenCalledWith('saveLearnerContext');
    expect(updateLearnerContext).toHaveBeenCalledWith('topic-a', 'conversation-a', {
      expected_revision: 4,
      include_cv: true,
    });
    expect(result.current.preference).toEqual(apiState(5, true));
    expect(activityApi.end).toHaveBeenCalledOnce();
  });

  test('retains the server value and exposes conflicts instead of optimistically changing it', async () => {
    vi.mocked(getLearnerContext).mockResolvedValue(apiState(2, true));
    vi.mocked(updateLearnerContext).mockRejectedValue(new Error('revision conflict'));
    const activityApi = { begin: vi.fn(() => true), end: vi.fn() };
    const { result } = renderHook(() =>
      useLearnerContext({ topicId: 'topic-a', conversationId: 'conversation-a', activity: 'idle', activityApi }),
    );
    await waitFor(() => expect(result.current.preference?.include_cv).toBe(true));

    await act(async () => result.current.setIncludeCv(false));

    expect(result.current.preference).toEqual(apiState(2, true));
    expect(result.current.error).toMatch(/revision conflict/i);
  });
});
