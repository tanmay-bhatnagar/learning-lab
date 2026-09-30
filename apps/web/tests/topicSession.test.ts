import { describe, expect, test } from 'vitest';
import {
  filesRefreshed,
  goalSaved,
  inputChanged,
  topicLoaded,
  topicRequested,
  topicSessionReducer,
} from '../src/state/topicSession';

describe('topicSession', () => {
  test('topicRequested clears session fields and marks loading', () => {
    const next = topicRequested();
    expect(next.messages).toEqual([]);
    expect(next.topicLoading).toBe(true);
    expect(next.input).toBe('');
  });

  test('topicLoaded preserves in-flight input across load completion', () => {
    const loading = { ...topicRequested(), input: '' };
    const withInput = inputChanged(loading, 'typed during load');
    const next = topicLoaded(withInput, {
      messages: [{ role: 'user', content: 'loaded' }],
      context: { used: 2 },
      files: [{ id: 'f', name: 'a.pdf', status: 'ready', parser: 'docling' }],
      topic: { id: 't', name: 'T', learning_goal: 'Learn' },
    });
    expect(next.input).toBe('typed during load');
    expect(next.goalDraft).toBe('Learn');
    expect(next.topicReady).toBe(true);
  });

  test('filesRefreshed keeps selection only for existing files', () => {
    const next = filesRefreshed({ ...empty(), selected: ['keep', 'drop'], files: [] }, [
      { id: 'keep', name: 'stay.pdf', status: 'ready', parser: 'docling' },
    ]);
    expect(next.selected).toEqual(['keep']);
  });

  test('goalSaved updates draft and notice', () => {
    const next = goalSaved(empty(), 'Saved goal');
    expect(next.learningGoal).toBe('Saved goal');
    expect(next.goalNotice).toMatch(/saved/i);
  });

  test('selectionChanged replaces selected ids', () => {
    const next = topicSessionReducer(
      { ...empty(), selected: ['a'] },
      { type: 'selectionChanged', selected: ['a', 'b'] },
    );
    expect(next.selected).toEqual(['a', 'b']);
  });
});

function empty() {
  return {
    messages: [],
    files: [],
    selected: [],
    context: {},
    learningGoal: '',
    goalDraft: '',
    goalNotice: '',
    topicReady: false,
    topicLoading: false,
    input: '',
  };
}
