import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { useBootstrap } from '../src/hooks/useBootstrap';
import { useSettings } from '../src/hooks/useSettings';
import { useActivity } from '../src/hooks/useActivity';
import { normalizeSettings } from '../src/modelControls';

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('../src/api/client', () => ({
  api,
  json: (body: unknown, method: string) => ({ body: JSON.stringify(body), method }),
}));

const saved = {
  model: 'example',
  context_limit: 8192,
  parser: 'docling',
  embedding_model: 'nomic-embed-text',
  retrieval_top_k: 6,
};

beforeEach(() => {
  api.mockReset();
  api.mockImplementation((path: string) => {
    if (path === '/topics') return Promise.resolve({ topics: [] });
    if (path === '/models') return Promise.resolve({ models: [] });
    return Promise.resolve(saved);
  });
});

describe('bootstrap settings', () => {
  test('keeps a saved 8192 context limit without writing settings during bootstrap', async () => {
    expect(normalizeSettings(saved)).toEqual({ settings: saved, migrated: false });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.settings.context_limit).toBe(8192);
    expect(result.current.settingsReady).toBe(true);
    expect(api.mock.calls.filter(([path]) => path === '/settings')).toHaveLength(1);
    expect(api.mock.calls.every(([, , init]) => init === undefined)).toBe(true);
  });

  test('keeps settings GET failure visible until a successful retry', async () => {
    api.mockImplementation((path: string) => {
      if (path === '/topics') return Promise.resolve({ topics: [] });
      if (path === '/models') return Promise.resolve({ models: [] });
      return Promise.reject(new Error('offline'));
    });
    const { result } = renderHook(() => useBootstrap());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.migrationError).toBe('Could not load settings: offline');
    expect(result.current.settingsReady).toBe(false);
    act(() => result.current.setError(''));
    expect(result.current.migrationError).toBe('Could not load settings: offline');

    api.mockImplementation((path: string) => {
      if (path === '/topics') return Promise.resolve({ topics: [] });
      if (path === '/models') return Promise.resolve({ models: [] });
      return Promise.resolve(saved);
    });
    await act(async () => result.current.initialize());
    expect(result.current.migrationError).toBe('');
    expect(result.current.settingsReady).toBe(true);
    expect(result.current.settings.context_limit).toBe(8192);
  });

  test('save and model selection cannot write until settings are ready', async () => {
    const alternative = { id: 'alternative', name: 'alternative', thinking: { type: 'none' as const } };
    const { result, rerender } = renderHook(
      ({ ready }) => {
        const activity = useActivity();
        return {
          ui: useSettings(saved, vi.fn(), vi.fn(), [alternative], vi.fn(), vi.fn(), activity.activity, activity, ready),
          ready,
          activity: activity.activity,
        };
      },
      { initialProps: { ready: false } },
    );
    await act(async () => {
      await result.current.ui.saveDraft();
      result.current.ui.selectModel(alternative.id);
    });
    expect(api.mock.calls.filter(([path, , init]) => path === '/settings' && init?.method === 'PUT')).toHaveLength(0);

    rerender({ ready: true });
    expect(result.current.ready).toBe(true);
    expect(result.current.activity).toBe('idle');
    await act(async () => {
      await result.current.ui.saveDraft();
    });
    expect(api.mock.calls).toEqual([['/settings', expect.anything(), expect.objectContaining({ method: 'PUT' })]]);
    await act(async () => result.current.ui.selectModel(alternative.id));
    expect(api.mock.calls.filter(([path, , init]) => path === '/settings' && init?.method === 'PUT')).toHaveLength(2);
  });
});
