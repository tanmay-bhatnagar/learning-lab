import { describe, expect, test } from 'vitest';
import { inputChanged, topicLoaded, topicRequested } from '../src/state/topicSession';

describe('topic load input preservation', () => {
  test('topicLoaded keeps in-flight input (86602ad did not clear on complete)', () => {
    const loading = topicRequested();
    const withInput = inputChanged(loading, 'typed during load');
    const loaded = topicLoaded(withInput, {
      messages: [{ role: 'user', content: 'Hello' }],
      context: {},
      files: [],
      topic: { id: 'topic-b', name: 'Topic B' },
    });
    expect(loaded.input).toBe('typed during load');
  });

  test('topicRequested still clears input at load start like 86602ad', () => {
    expect(topicRequested().input).toBe('');
  });
});
