import { describe, expect, test } from 'vitest';
import { canStart, deriveActivity, uploadBlockedReason } from '../src/state/activity';

describe('activity', () => {
  test('deriveActivity maps flags and locks to one activity', () => {
    expect(deriveActivity(emptyFlags())).toBe('idle');
    expect(deriveActivity({ ...emptyFlags(), sending: true })).toBe('sending');
    expect(deriveActivity({ ...emptyFlags(), streamLocked: true })).toBe('sending');
    expect(deriveActivity({ ...emptyFlags(), persistenceLocked: true })).toBe('savingSettings');
  });

  test('canStart allows work only when idle', () => {
    expect(canStart('idle', 'send')).toBe(true);
    expect(canStart('uploading', 'send')).toBe(false);
  });

  test('uploadBlockedReason mirrors upload guard messages', () => {
    expect(uploadBlockedReason('idle', { hasTopic: false, topicReady: true })).toMatch(/Choose a topic/i);
    expect(uploadBlockedReason('sending', { hasTopic: true, topicReady: true })).toMatch(/Finish the current action/i);
  });
});

function emptyFlags() {
  return {
    sending: false,
    uploading: false,
    saving: false,
    goalSaving: false,
    creating: false,
    streamLocked: false,
    uploadLocked: false,
    persistenceLocked: false,
  };
}
