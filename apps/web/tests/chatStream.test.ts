import { describe, expect, test } from 'vitest';
import { applyStreamEvent, failTurn, startTurn } from '../src/state/chatStream';

describe('chatStream', () => {
  test('startTurn appends user and empty assistant placeholders', () => {
    const next = startTurn([], 'Hello');
    expect(next).toHaveLength(2);
    expect(next[0]).toEqual({ role: 'user', content: 'Hello' });
    expect(next[1].role).toBe('assistant');
  });

  test('applyStreamEvent folds thinking, token, model and retrieval onto the last message', () => {
    let messages = startTurn([], 'Hi');
    messages = applyStreamEvent(messages, { type: 'thinking', text: 'Plan' });
    messages = applyStreamEvent(messages, { type: 'token', text: 'Answer' });
    messages = applyStreamEvent(messages, {
      type: 'done',
      model: 'qwen3.5:9b',
      retrieval: { mode: 'none', citations: [] },
    });
    expect(messages.at(-1)).toMatchObject({
      thinking: 'Plan',
      content: 'Answer',
      model: 'qwen3.5:9b',
      retrieval: { mode: 'none', citations: [] },
    });
  });

  test('failTurn marks the assistant message incomplete', () => {
    const messages = startTurn([], 'Hi');
    expect(failTurn(messages, true).messages.at(-1)?.incomplete).toBe(true);
  });
});
