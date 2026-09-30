import { describe, expect, test } from 'vitest';
import { activityForOp, canStart, isBusy, uploadBlockedReason } from '../src/state/activity';

describe('activity', () => {
  test('activityForOp maps operations to activity labels', () => {
    expect(activityForOp('send')).toBe('sending');
    expect(activityForOp('selectModel')).toBe('savingSettings');
    expect(activityForOp('createTopic')).toBe('creatingTopic');
  });

  test('isBusy matches original busy flag semantics', () => {
    expect(isBusy('idle')).toBe(false);
    expect(isBusy('creatingTopic')).toBe(false);
    expect(isBusy('sending')).toBe(true);
    expect(isBusy('uploading')).toBe(true);
    expect(isBusy('savingSettings')).toBe(true);
    expect(isBusy('savingGoal')).toBe(true);
  });

  test('canStart allows only idle operations', () => {
    expect(canStart('idle', 'send')).toBe(true);
    expect(canStart('idle', 'createTopic')).toBe(true);
    expect(canStart('sending', 'upload')).toBe(false);
    expect(canStart('uploading', 'saveSettings')).toBe(false);
    expect(canStart('creatingTopic', 'createTopic')).toBe(false);
  });

  test('uploadBlockedReason mirrors upload guard messages', () => {
    expect(uploadBlockedReason('idle', { hasTopic: false, topicReady: true })).toMatch(/Choose a topic/i);
    expect(uploadBlockedReason('sending', { hasTopic: true, topicReady: true })).toMatch(/Finish the current action/i);
    expect(uploadBlockedReason('creatingTopic', { hasTopic: true, topicReady: true })).toMatch(
      /Finish the current action/i,
    );
  });
});
