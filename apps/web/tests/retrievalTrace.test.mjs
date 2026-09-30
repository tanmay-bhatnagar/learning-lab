import { test } from 'vitest';
import assert from 'node:assert/strict';

import {
  chunkDisplayText,
  formatRank,
  formatTraceScore,
  indexedSelectedIds,
  isIndexedFile,
  modeLabel,
  resolveAssetId,
  traceRequest,
} from '../src/retrievalTraceHelpers';
import { assetApiUrl } from '../src/api/urls';

const indexed = { id: 'a', name: 'paper.pdf', status: 'ready', parser: 'docling', index_status: 'ready' };
const legacy = { id: 'b', name: 'notes.pdf', status: 'ready', parser: 'markitdown', index_status: undefined };
const assets = [{ id: 'fig-1', name: 'paper.figure-1.png', kind: 'figure', page: 2 }];

test('indexed selection keeps only ready indexed files and dedupes trace requests', () => {
  assert.equal(isIndexedFile(indexed), true);
  assert.equal(isIndexedFile(legacy), false);
  assert.deepEqual(indexedSelectedIds([indexed, legacy], ['a', 'b', 'a']), ['a']);
  assert.deepEqual(traceRequest('  calibration  ', ['a', 'a'], 6), {
    query: 'calibration',
    file_ids: ['a'],
    top_k: 6,
  });
});

test('asset refs resolve stored names to API asset ids and build file-scoped URLs', () => {
  const file = { ...indexed, assets };
  assert.equal(resolveAssetId(file, 'fig-1'), 'fig-1');
  assert.equal(resolveAssetId(file, 'paper.figure-1.png'), 'fig-1');
  assert.equal(resolveAssetId(file, 'missing.png'), null);
  assert.equal(assetApiUrl('topic-1', 'a', 'fig-1'), '/api/topics/topic-1/files/a/assets/fig-1');
});

test('trace formatting exposes ranks, BM25, cosine, and mode labels', () => {
  assert.equal(formatRank(null), '—');
  assert.equal(formatRank(2), '#2');
  assert.equal(formatTraceScore({ rank: 1, score: -3.456 }, 'keyword'), '-3.456');
  assert.equal(formatTraceScore({ rank: 1, score: 0.8123, cosine: 0.8123 }, 'embedding'), '0.8123');
  assert.equal(formatTraceScore({ rank: 1, score: 0.016393 }, 'fusion'), '0.01639');
  assert.equal(modeLabel('hybrid'), 'Hybrid (keyword + embeddings + RRF)');
  assert.equal(chunkDisplayText({ contextualized_text: 'Heading\nBody' }), 'Heading\nBody');
});
