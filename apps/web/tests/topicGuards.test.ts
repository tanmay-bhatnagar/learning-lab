import { describe, expect, test } from 'vitest';
import { goalSaved } from '../src/state/topicSession';

export function applyGoalSaveIfCurrent(
  currentTopic: string,
  targetTopic: string,
  state: Parameters<typeof goalSaved>[0],
  learningGoal: string,
) {
  if (currentTopic !== targetTopic) return state;
  return goalSaved(state, learningGoal);
}

describe('topic response guards', () => {
  test('goal save ignores stale response after topic switch', () => {
    const before = {
      messages: [],
      files: [],
      selected: [],
      context: {},
      learningGoal: 'Learn B',
      goalDraft: 'Learn B',
      goalNotice: '',
      topicReady: true,
      topicLoading: false,
      input: '',
    };
    const after = applyGoalSaveIfCurrent('topic-b', 'topic-a', before, 'Goal for A');
    expect(after.goalDraft).toBe('Learn B');
    expect(after.learningGoal).toBe('Learn B');
    expect(after.goalNotice).toBe('');
  });
});
