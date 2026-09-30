export type Activity = 'idle' | 'sending' | 'uploading' | 'savingSettings' | 'savingGoal' | 'creatingTopic';

export type ActivityOp = 'send' | 'upload' | 'saveSettings' | 'saveGoal' | 'createTopic' | 'selectModel';

export type ActivityInput = {
  sending: boolean;
  uploading: boolean;
  saving: boolean;
  goalSaving: boolean;
  creating: boolean;
  streamLocked: boolean;
  uploadLocked: boolean;
  persistenceLocked: boolean;
};

export function deriveActivity(input: ActivityInput): Activity {
  if (input.sending || input.streamLocked) return 'sending';
  if (input.uploading || input.uploadLocked) return 'uploading';
  if (input.saving || input.persistenceLocked) return 'savingSettings';
  if (input.goalSaving) return 'savingGoal';
  if (input.creating) return 'creatingTopic';
  return 'idle';
}

export function isBusy(activity: Activity): boolean {
  return activity !== 'idle';
}

export function canStart(activity: Activity, op: ActivityOp): boolean {
  void op;
  return activity === 'idle';
}

export function uploadBlockedReason(
  activity: Activity,
  options: { topicReady: boolean; hasTopic: boolean },
): string | null {
  if (!options.hasTopic) return 'Choose a topic before adding PDFs.';
  if (!options.topicReady) return 'Wait for this topic to finish loading before adding files.';
  if (isBusy(activity)) return 'Finish the current action before adding files.';
  return null;
}
