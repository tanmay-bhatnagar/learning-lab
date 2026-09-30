import { describe, expect, test, vi, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useThinkingPrefs } from '../src/hooks/useThinkingPrefs';

describe('useThinkingPrefs', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test('reports localStorage write failures', async () => {
    const original = window.localStorage.setItem.bind(window.localStorage);
    vi.spyOn(window.localStorage, 'setItem').mockImplementation((key, value) => {
      if (key === 'lab-thinking') throw new Error('quota');
      original(key, value);
    });
    const { result } = renderHook(() => useThinkingPrefs());
    expect(result.current.storageError).toMatch(/Thinking preferences could not be saved/i);
    result.current.setThink(true, 'model-a');
    await waitFor(() => expect(result.current.storageError).toMatch(/Thinking preferences could not be saved/i));
  });
});
