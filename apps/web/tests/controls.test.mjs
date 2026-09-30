import { test } from 'vitest';
import assert from 'node:assert/strict';
import { File } from 'node:buffer';
import {
  APP_CONTEXT_MAX,
  LEGACY_CONTEXT_LIMIT,
  modelLabel,
  modelContextMax,
  modelSelection,
  normalizeSettings,
  quantizationLabel,
  validateContext,
  thinkingValue,
  chatRequest,
} from '../src/modelControls';
import { pdfDropBlocked, validatePdfs, MAX_PDF_BYTES } from '../src/uploads';
import { canSaveLearningGoal, MAX_LEARNING_GOAL_CHARS } from '../src/learningGoal';
const qwen = { id: 'qwen3.5:9b-q4_K_M', name: 'qwen3.5:9b-q4_K_M', thinking: { type: 'toggle' } };
test('model labels prefer server display name and format known IDs without technical quantization suffixes', () => {
  assert.equal(modelLabel(qwen), 'Qwen 3.5 · 9B · 4-bit');
  assert.equal(modelLabel('qwen3.5:4b-q8_0'), 'Qwen 3.5 · 4B · 8-bit');
  assert.equal(modelLabel({ ...qwen, display_name: 'Custom model' }), 'Custom model');
  assert.equal(modelLabel('gpt-oss:20b'), 'GPT-OSS · 20B');
  assert.equal(modelLabel('unknown-model:latest'), 'unknown-model');
  assert.equal(quantizationLabel('q4_K_M'), '4-bit');
  assert.equal(quantizationLabel('fp16'), undefined);
});
test('app context default and maximum stay at 32768 regardless of model metadata', () => {
  const saved = { model: 'previous', context_limit: LEGACY_CONTEXT_LIMIT, parser: 'anydoc' };
  const selected = modelSelection(saved, qwen);
  assert.deepEqual(saved, { model: 'previous', context_limit: LEGACY_CONTEXT_LIMIT, parser: 'anydoc' });
  assert.deepEqual(selected, { model: qwen.id, context_limit: APP_CONTEXT_MAX, parser: 'anydoc' });
  assert.equal(modelContextMax({ ...qwen, max_context_length: 262144 }), APP_CONTEXT_MAX);
  assert.equal(modelContextMax({ ...qwen, max_context_length: 16384 }), APP_CONTEXT_MAX);
  assert.equal(modelContextMax({ ...qwen, max_context_length: -1 }), APP_CONTEXT_MAX);
  assert.equal(validateContext(APP_CONTEXT_MAX, qwen), undefined);
  assert.equal(validateContext(APP_CONTEXT_MAX, { ...qwen, max_context_length: 16384 }), undefined);
  for (const value of [1023, 32769, NaN, 2048.5]) assert.ok(validateContext(value, qwen));
});
test('legacy saved 8192 context migrates to 32768 during initialization normalization', () => {
  assert.deepEqual(
    normalizeSettings({ model: 'qwen3.5:9b-q4_K_M', context_limit: LEGACY_CONTEXT_LIMIT, parser: 'anydoc' }),
    {
      settings: {
        model: 'qwen3.5:9b-q4_K_M',
        context_limit: APP_CONTEXT_MAX,
        parser: 'anydoc',
        embedding_model: 'nomic-embed-text',
        retrieval_top_k: 6,
      },
      migrated: true,
    },
  );
  assert.deepEqual(
    normalizeSettings({ model: 'qwen3.5:9b-q4_K_M', context_limit: APP_CONTEXT_MAX, parser: 'anydoc' }),
    {
      settings: {
        model: 'qwen3.5:9b-q4_K_M',
        context_limit: APP_CONTEXT_MAX,
        parser: 'anydoc',
        embedding_model: 'nomic-embed-text',
        retrieval_top_k: 6,
      },
      migrated: false,
    },
  );
  assert.deepEqual(
    normalizeSettings({ model: 'qwen3.5:9b-q4_K_M', context_limit: 16384, parser: 'anydoc' }).migrated,
    false,
  );
});
test('next chat request uses saved selected model/context and actual thinking capabilities', () => {
  const settings = modelSelection({ model: 'previous', context_limit: LEGACY_CONTEXT_LIMIT, parser: 'anydoc' }, qwen);
  assert.deepEqual(chatRequest(settings, qwen, { [qwen.id]: true }, 'Hello', ['pdf1']), {
    message: 'Hello',
    file_ids: ['pdf1'],
    model: qwen.id,
    context_limit: APP_CONTEXT_MAX,
    think: true,
  });
  assert.equal(thinkingValue(qwen, { [qwen.id]: 'high' }), false);
  const oss = { id: 'gpt-oss:20b', thinking: { type: 'levels', levels: ['low', 'medium', 'high'] } };
  assert.equal(thinkingValue(oss, { [oss.id]: 'high' }), 'high');
  assert.equal(thinkingValue(oss, { [oss.id]: true }), 'low');
  assert.equal(thinkingValue({ ...qwen, thinking: { type: 'none' } }, {}), undefined);
  assert.equal(
    thinkingValue(
      { ...qwen, thinking: { type: 'levels', levels: ['low', 'medium', 'high'] } },
      { [qwen.id]: 'medium' },
    ),
    'medium',
  );
});
test('PDF drop eligibility explains blocked uploads before validation runs', () => {
  assert.equal(pdfDropBlocked({ busy: false, topicReady: true, hasTopic: true }), null);
  assert.match(pdfDropBlocked({ busy: true, topicReady: true, hasTopic: true }), /current action/);
  assert.match(pdfDropBlocked({ busy: false, topicReady: false, hasTopic: true }), /finish loading/);
  assert.match(pdfDropBlocked({ busy: false, topicReady: true, hasTopic: false }), /Choose a topic/);
});
test('learning goal saves only a changed, bounded draft for a fully loaded idle topic', () => {
  const ready = { hasTopic: true, topicReady: true, busy: false, draft: 'Learn eigenvectors', saved: '' };
  assert.equal(canSaveLearningGoal(ready), true);
  assert.equal(canSaveLearningGoal({ ...ready, topicReady: false }), false);
  assert.equal(canSaveLearningGoal({ ...ready, hasTopic: false }), false);
  assert.equal(canSaveLearningGoal({ ...ready, busy: true }), false);
  assert.equal(canSaveLearningGoal({ ...ready, saved: ready.draft }), false);
  assert.equal(canSaveLearningGoal({ ...ready, draft: 'x'.repeat(MAX_LEARNING_GOAL_CHARS) }), true);
  assert.equal(canSaveLearningGoal({ ...ready, draft: 'x'.repeat(MAX_LEARNING_GOAL_CHARS + 1) }), false);
  assert.equal(canSaveLearningGoal({ ...ready, draft: '', saved: 'Old goal' }), true);
});
test('PDF browse/drop validation accepts valid PDFs including blank browser MIME', async () => {
  await validatePdfs([
    new File(['%PDF-1.7\ncontent'], 'Reading.PDF', { type: 'application/pdf' }),
    new File(['%PDF-1.4'], 'second.pdf'),
  ]);
});
test('PDF validation rejects wrong extension, MIME, empty, oversized, and disguised files before upload', async () => {
  const cases = [
    [new File(['%PDF-'], 'notes.txt'), /not a PDF/],
    [new File(['%PDF-'], 'notes.pdf', { type: 'text/plain' }), /not a PDF/],
    [new File([], 'empty.pdf'), /empty/],
    [{ name: 'large.pdf', type: 'application/pdf', size: MAX_PDF_BYTES + 1 }, /25 MiB/],
    [new File(['not a PDF'], 'fake.pdf'), /PDF header/],
  ];
  for (const [file, error] of cases)
    await assert.rejects(validatePdfs([new File(['%PDF-'], 'valid.pdf'), file]), error);
});
