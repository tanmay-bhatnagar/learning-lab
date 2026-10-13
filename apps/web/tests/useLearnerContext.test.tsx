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
    expect(updateLearnerContext).toHaveBeenCalledWith(
      'topic-a',
      'conversation-a',
      {
        expected_revision: 4,
        include_cv: true,
      },
      expect.any(AbortSignal),
    );
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

  test('aborts stale loads and adopts only the newly selected conversation', async () => {
    let finishFirst: ((value: ReturnType<typeof apiState>) => void) | undefined;
    vi.mocked(getLearnerContext)
      .mockImplementationOnce(() => new Promise((resolve) => (finishFirst = resolve)))
      .mockResolvedValueOnce(apiState(7, true));
    const activityApi = { begin: vi.fn(() => true), end: vi.fn() };
    const { result, rerender } = renderHook(
      ({ conversationId }: { conversationId: string }) =>
        useLearnerContext({ topicId: 'topic-a', conversationId, activity: 'idle', activityApi }),
      { initialProps: { conversationId: 'conversation-a' } },
    );
    await waitFor(() => expect(getLearnerContext).toHaveBeenCalledTimes(1));

    rerender({ conversationId: 'conversation-b' });
    await waitFor(() => expect(result.current.preference?.revision).toBe(7));
    await act(async () => finishFirst?.(apiState(3, false)));

    expect(result.current.preference).toEqual(apiState(7, true));
    expect(vi.mocked(getLearnerContext).mock.calls[0]?.[2]?.aborted).toBe(true);
  });

  test('clears an earlier target error when a fresh load later succeeds', async () => {
    vi.mocked(getLearnerContext)
      .mockRejectedValueOnce(new Error('temporary failed load'))
      .mockResolvedValueOnce(apiState(2, false))
      .mockResolvedValueOnce(apiState(3, true));
    const activityApi = { begin: vi.fn(() => true), end: vi.fn() };
    const { result, rerender } = renderHook(
      ({ conversationId }: { conversationId: string }) =>
        useLearnerContext({ topicId: 'topic-a', conversationId, activity: 'idle', activityApi }),
      { initialProps: { conversationId: 'conversation-a' } },
    );

    await waitFor(() => expect(result.current.error).toBe('temporary failed load'));

    rerender({ conversationId: 'conversation-b' });
    await waitFor(() => expect(result.current.preference?.revision).toBe(2));
    expect(result.current.error).toBe('');

    rerender({ conversationId: 'conversation-a' });
    await waitFor(() => expect(result.current.preference?.revision).toBe(3));
    expect(result.current.error).toBe('');
  });
});
