export const MAX_LEARNING_GOAL_CHARS = 2000;

export type GoalSaveInput = { hasTopic: boolean; topicReady: boolean; busy: boolean; draft: string; saved: string };

export function canSaveLearningGoal({ hasTopic, topicReady, busy, draft, saved }: GoalSaveInput): boolean {
  return hasTopic && topicReady && !busy && draft !== saved && draft.length <= MAX_LEARNING_GOAL_CHARS;
}
