import { describe, expect, test } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useActivity } from '../src/hooks/useActivity';

describe('useActivity', () => {
  test('begin and end drive a single activity owner', () => {
    const { result } = renderHook(() => useActivity());
    expect(result.current.activity).toBe('idle');

    let started = false;
    act(() => {
      started = result.current.begin('send');
    });
    expect(started).toBe(true);
    expect(result.current.activity).toBe('sending');

    act(() => {
      expect(result.current.begin('upload')).toBe(false);
    });

    act(() => {
      result.current.end();
    });
    expect(result.current.activity).toBe('idle');
  });

  test('mirror ref blocks same-tick re-entry before render', () => {
    const { result } = renderHook(() => useActivity());
    act(() => {
      expect(result.current.begin('upload')).toBe(true);
      expect(result.current.begin('upload')).toBe(false);
      result.current.end();
    });
  });
});
