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
  input: '',
});

export function topicRequested(): TopicSessionState {
  return { ...emptyTopicSession(), topicLoading: true };
}

export function conversationRequested(previous: TopicSessionState): TopicSessionState {
  return { ...previous, messages: [], context: {}, input: '', topicReady: false, topicLoading: true };
}

export function topicLoaded(
  previous: TopicSessionState,
  payload: {
    messages: Message[];
    context: Context;
    files: LabFile[];
    selected?: string[];
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
    goalDraft: previous.goalDraft === previous.learningGoal ? goal : previous.goalDraft,
    goalNotice: '',
    topicReady: true,
    topicLoading: false,
    selected: payload.selected || [],
  };
}

export function topicFailed(previous: TopicSessionState): TopicSessionState {
  return { ...previous, topicReady: false, topicLoading: false };
}

export function inputChanged(previous: TopicSessionState, value: string): TopicSessionState {
  return { ...previous, input: value };
}

export function goalDraftChanged(previous: TopicSessionState, value: string): TopicSessionState {
  return { ...previous, goalDraft: value };
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

export function selectionChanged(previous: TopicSessionState, selected: string[]): TopicSessionState {
  return { ...previous, selected };
}

export function fileUploaded(previous: TopicSessionState, file: LabFile): TopicSessionState {
  return {
    ...previous,
    files: [...previous.files.filter((entry) => entry.id !== file.id), file],
  };
}

export function messagesChanged(
  previous: TopicSessionState,
  value: Message[] | ((messages: Message[]) => Message[]),
): TopicSessionState {
  const messages = typeof value === 'function' ? value(previous.messages) : value;
  return { ...previous, messages };
}

export function contextChanged(previous: TopicSessionState, context: Context): TopicSessionState {
  return { ...previous, context };
}

export function conversationHistoryReplaced(
  previous: TopicSessionState,
  payload: { messages: Message[]; context: Context },
): TopicSessionState {
  return { ...previous, messages: payload.messages, context: payload.context };
}

export type TopicSessionAction =
  | { type: 'topicRequested' }
  | { type: 'conversationRequested' }
  | {
      type: 'topicLoaded';
      payload: { messages: Message[]; context: Context; files: LabFile[]; selected?: string[]; topic: Topic };
    }
  | { type: 'topicFailed' }
  | { type: 'inputChanged'; value: string }
  | { type: 'goalDraftChanged'; value: string }
  | { type: 'selectionToggled'; fileId: string; checked: boolean }
  | { type: 'selectionChanged'; selected: string[] }
  | { type: 'filesRefreshed'; files: LabFile[] }
  | { type: 'goalSaved'; learningGoal: string }
  | { type: 'fileUploaded'; file: LabFile }
  | { type: 'messagesChanged'; value: Message[] | ((messages: Message[]) => Message[]) }
  | { type: 'contextChanged'; context: Context }
  | { type: 'conversationHistoryReplaced'; messages: Message[]; context: Context };

export function topicSessionReducer(state: TopicSessionState, action: TopicSessionAction): TopicSessionState {
  switch (action.type) {
    case 'topicRequested':
      return topicRequested();
    case 'conversationRequested':
      return conversationRequested(state);
    case 'topicLoaded':
      return topicLoaded(state, action.payload);
    case 'topicFailed':
      return topicFailed(state);
    case 'inputChanged':
      return inputChanged(state, action.value);
    case 'goalDraftChanged':
      return goalDraftChanged(state, action.value);
    case 'selectionToggled':
      return selectionToggled(state, action.fileId, action.checked);
    case 'selectionChanged':
      return selectionChanged(state, action.selected);
    case 'filesRefreshed':
      return filesRefreshed(state, action.files);
    case 'goalSaved':
      return goalSaved(state, action.learningGoal);
    case 'fileUploaded':
      return fileUploaded(state, action.file);
    case 'messagesChanged':
      return messagesChanged(state, action.value);
    case 'contextChanged':
      return contextChanged(state, action.context);
    case 'conversationHistoryReplaced':
      return conversationHistoryReplaced(state, { messages: action.messages, context: action.context });
    default:
      return state;
  }
}
