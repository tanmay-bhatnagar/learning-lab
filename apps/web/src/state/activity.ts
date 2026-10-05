export type Activity =
  | 'idle'
  | 'sending'
  | 'uploading'
  | 'savingSettings'
  | 'savingGoal'
  | 'buildingMap'
  | 'generatingSummary'
  | 'importingSummary';

export type ActivityOp =
  | 'send'
  | 'upload'
  | 'saveSettings'
  | 'saveGoal'
  | 'selectModel'
  | 'buildMap'
  | 'generateSummary'
  | 'importSummary';

export function activityForOp(op: ActivityOp): Activity {
  switch (op) {
    case 'send':
      return 'sending';
    case 'upload':
      return 'uploading';
    case 'saveSettings':
    case 'selectModel':
      return 'savingSettings';
    case 'saveGoal':
      return 'savingGoal';
    case 'buildMap':
      return 'buildingMap';
    case 'generateSummary':
      return 'generatingSummary';
    case 'importSummary':
      return 'importingSummary';
  }
}

export function isBusy(activity: Activity): boolean {
  return activity !== 'idle';
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
