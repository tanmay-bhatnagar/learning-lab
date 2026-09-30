import { describe, expect, test } from 'vitest';
import { filesRefreshed, topicLoaded, topicRequested } from '../src/state/topicSession';

describe('topicSession', () => {
  test('topicRequested clears session fields and marks loading', () => {
    const next = topicRequested({
      messages: [{ role: 'user', content: 'old' }],
      files: [{ id: 'f', name: 'a.pdf', status: 'ready', parser: 'docling' }],
      selected: ['f'],
      context: { used: 1 },
      learningGoal: 'goal',
      goalDraft: 'draft',
      goalNotice: 'saved',
      topicReady: true,
      topicLoading: false,
      preview: null,
      input: 'typed',
    });
    expect(next.messages).toEqual([]);
    expect(next.topicLoading).toBe(true);
    expect(next.input).toBe('');
  });

  test('topicLoaded restores server state', () => {
    const next = topicLoaded(topicRequested({ ...empty(), topicLoading: true }), {
      messages: [{ role: 'user', content: 'loaded' }],
      context: { used: 2 },
      files: [{ id: 'f', name: 'a.pdf', status: 'ready', parser: 'docling' }],
      topic: { id: 't', name: 'T', learning_goal: 'Learn' },
    });
    expect(next.messages[0].content).toBe('loaded');
    expect(next.goalDraft).toBe('Learn');
    expect(next.topicReady).toBe(true);
  });

  test('filesRefreshed keeps selection only for existing files', () => {
    const next = filesRefreshed({ ...empty(), selected: ['keep', 'drop'], files: [] }, [
      { id: 'keep', name: 'stay.pdf', status: 'ready', parser: 'docling' },
    ]);
    expect(next.selected).toEqual(['keep']);
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
    preview: null,
    input: '',
  };
}
