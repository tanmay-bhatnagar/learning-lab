import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import * as client from '../src/api/client';
import { useActivity } from '../src/hooks/useActivity';
import { useUploads } from '../src/hooks/useUploads';
import * as uploads from '../src/uploads';

const pdf = (name: string) => new File(['%PDF-test'], name, { type: 'application/pdf' });
const deferred = () => {
  let resolve!: (value: never) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<never>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
};

beforeEach(() => {
  vi.spyOn(uploads, 'validatePdfs').mockResolvedValue();
});

describe('useUploads cancellation', () => {
  test('topic change aborts the pending request and stops the batch', async () => {
    const pending = deferred();
    const request = vi.spyOn(client, 'api').mockImplementation(() => pending.promise);
    const topicRef = { current: 'a' };
    const setError = vi.fn();
    const appendFile = vi.fn();
    const { result, rerender } = renderHook(
      ({ topic }) => {
        const activity = useActivity();
        return { activity, uploads: useUploads(topic, topicRef, activity.activity, true, activity) };
      },
      { initialProps: { topic: 'a' } },
    );

    let finished!: Promise<void>;
    act(() => {
      finished = result.current.uploads.upload([pdf('one.pdf'), pdf('two.pdf')], 'docling', setError, appendFile);
    });
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    const signal = request.mock.calls[0][2]?.signal;
    expect(signal?.aborted).toBe(false);

    topicRef.current = 'b';
    rerender({ topic: 'b' });
    expect(signal?.aborted).toBe(true);
    expect(result.current.activity.activity).toBe('idle');

    act(() => pending.resolve({} as never));
    await act(async () => finished);
    expect(request).toHaveBeenCalledTimes(1);
    expect(appendFile).not.toHaveBeenCalled();
    expect(setError).toHaveBeenCalledWith('');
  });

  test('a cancelled batch cannot release a newer activity', async () => {
    const pending = deferred();
    vi.spyOn(client, 'api').mockImplementation(() => pending.promise);
    const topicRef = { current: 'a' };
    const { result, rerender } = renderHook(
      ({ topic }) => {
        const activity = useActivity();
        return { activity, uploads: useUploads(topic, topicRef, activity.activity, true, activity) };
      },
      { initialProps: { topic: 'a' } },
    );
    let finished!: Promise<void>;
    act(() => {
      finished = result.current.uploads.upload([pdf('one.pdf')], 'docling', vi.fn(), vi.fn());
    });
    await vi.waitFor(() => expect(client.api).toHaveBeenCalledTimes(1));
    topicRef.current = 'b';
    rerender({ topic: 'b' });
    act(() => expect(result.current.activity.begin('send')).toBe(true));
    act(() => pending.reject(new DOMException('Aborted', 'AbortError')));
    await act(async () => finished);
    expect(result.current.activity.activity).toBe('sending');
  });

  test('same-topic rerender preserves an upload and continues the batch', async () => {
    const first = deferred();
    const request = vi
      .spyOn(client, 'api')
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValue({} as never);
    const topicRef = { current: 'a' };
    const appendFile = vi.fn();
    const { result, rerender, unmount } = renderHook(
      ({ topic }) => {
        const activity = useActivity();
        return { activity, uploads: useUploads(topic, topicRef, activity.activity, true, activity) };
      },
      { initialProps: { topic: 'a' } },
    );
    let finished!: Promise<void>;
    act(() => {
      finished = result.current.uploads.upload([pdf('one.pdf'), pdf('two.pdf')], 'docling', vi.fn(), appendFile);
    });
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    const signal = request.mock.calls[0][2]?.signal;
    rerender({ topic: 'a' });
    expect(signal?.aborted).toBe(false);
    act(() => first.resolve({} as never));
    await act(async () => finished);
    expect(request).toHaveBeenCalledTimes(2);
    expect(appendFile).toHaveBeenCalledTimes(2);
    expect(result.current.activity.activity).toBe('idle');
    unmount();
  });

  test('unmount aborts a pending request', async () => {
    const pending = deferred();
    const request = vi.spyOn(client, 'api').mockImplementation(() => pending.promise);
    const topicRef = { current: 'a' };
    const { result, unmount } = renderHook(() => {
      const activity = useActivity();
      return useUploads('a', topicRef, activity.activity, true, activity);
    });
    let finished!: Promise<void>;
    act(() => {
      finished = result.current.upload([pdf('one.pdf')], 'docling', vi.fn(), vi.fn());
    });
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    const signal = request.mock.calls[0][2]?.signal;
    unmount();
    expect(signal?.aborted).toBe(true);
    act(() => pending.reject(new DOMException('Aborted', 'AbortError')));
    await finished;
  });
});
