import { describe, expect, test } from 'vitest';
import { activityForOp, canStart, isBusy, uploadBlockedReason } from '../src/state/activity';

describe('activity', () => {
  test('activityForOp maps operations to activity labels', () => {
    expect(activityForOp('send')).toBe('sending');
    expect(activityForOp('selectModel')).toBe('savingSettings');
    expect(activityForOp('saveGoal')).toBe('savingGoal');
  });

  test('isBusy matches original busy flag semantics (excludes topic creation)', () => {
    expect(isBusy('idle')).toBe(false);
    expect(isBusy('sending')).toBe(true);
    expect(isBusy('uploading')).toBe(true);
    expect(isBusy('savingSettings')).toBe(true);
    expect(isBusy('savingGoal')).toBe(true);
  });

  test('canStart allows any operation only when idle', () => {
    expect(canStart('idle', 'send')).toBe(true);
    expect(canStart('idle', 'upload')).toBe(true);
    expect(canStart('idle', 'saveSettings')).toBe(true);
    expect(canStart('sending', 'upload')).toBe(false);
    expect(canStart('uploading', 'saveSettings')).toBe(false);
    expect(canStart('savingGoal', 'send')).toBe(false);
  });

  test('uploadBlockedReason mirrors upload guard messages', () => {
    expect(uploadBlockedReason('idle', { hasTopic: false, topicReady: true })).toMatch(/Choose a topic/i);
    expect(uploadBlockedReason('sending', { hasTopic: true, topicReady: true })).toMatch(/Finish the current action/i);
    expect(uploadBlockedReason('idle', { hasTopic: true, topicReady: true })).toBeNull();
  });
});
