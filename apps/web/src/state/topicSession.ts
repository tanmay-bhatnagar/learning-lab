import type { Context, LabFile, Message, Topic } from '../api/types';

export type TopicSessionState = {
  messages: Message[];
  files: LabFile[];
  selected: string[];
  context: Context;
  learningGoal: string;
  goalDraft: string;
  goalNotice: string;
  topicReady: boolean;
  topicLoading: boolean;
  preview?: LabFile | null;
  input: string;
};

export const emptyTopicSession = (): TopicSessionState => ({
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
});

export function topicRequested(previous: TopicSessionState): TopicSessionState {
  void previous;
  return { ...emptyTopicSession(), topicLoading: true };
}

export function topicLoaded(
  previous: TopicSessionState,
  payload: {
    messages: Message[];
    context: Context;
    files: LabFile[];
    topic: Topic;
  },
): TopicSessionState {
  const goal = payload.topic.learning_goal || '';
  return {
    ...previous,
    messages: payload.messages,
    context: payload.context,
    files: payload.files,
    learningGoal: goal,
    goalDraft: goal,
    goalNotice: '',
    topicReady: true,
    topicLoading: false,
    preview: null,
    input: '',
    selected: [],
  };
}

export function topicFailed(previous: TopicSessionState): TopicSessionState {
  return { ...previous, topicReady: false, topicLoading: false };
}

export function goalSaved(previous: TopicSessionState, learningGoal: string): TopicSessionState {
  return {
    ...previous,
    learningGoal,
    goalDraft: learningGoal,
    goalNotice: 'Learning goal saved for this topic.',
  };
}

export function filesRefreshed(previous: TopicSessionState, files: LabFile[]): TopicSessionState {
  const ids = new Set(files.map((file) => file.id));
  return {
    ...previous,
    files,
    selected: previous.selected.filter((id) => ids.has(id)),
  };
}

export function selectionToggled(previous: TopicSessionState, fileId: string, checked: boolean): TopicSessionState {
  const selected = checked ? [...previous.selected, fileId] : previous.selected.filter((id) => id !== fileId);
  return { ...previous, selected };
}

export function fileUploaded(previous: TopicSessionState, file: LabFile): TopicSessionState {
  return {
    ...previous,
    files: [...previous.files.filter((entry) => entry.id !== file.id), file],
  };
}
