import { test } from 'vitest';
import assert from 'node:assert/strict';

import {
  citationChunkLabel,
  hasSources,
  modeBadgeLabel,
  sourcesButtonLabel,
  sourcesCount,
} from '../src/citationsHelpers';
import { originalPdfUrl } from '../src/api';

test('sources helpers count citations and build button labels', () => {
  const retrieval = { mode: 'keyword', citations: [{ chunk_id: 'a' }, { chunk_id: 'b' }] };
  assert.equal(sourcesCount(undefined), 0);
  assert.equal(sourcesCount(retrieval), 2);
  assert.equal(hasSources(retrieval), true);
  assert.equal(hasSources({ mode: 'none', citations: [] }), false);
  assert.equal(hasSources({ mode: 'fallback', citations: [], warning: 'No matches were available.' }), true);
  assert.equal(sourcesButtonLabel(3), 'Sources (3)');
});

test('citation labels expose mode badges and chunk numbers', () => {
  assert.equal(modeBadgeLabel('hybrid'), 'Hybrid (keyword + embeddings + RRF)');
  assert.equal(modeBadgeLabel('none'), 'No retrieval');
  assert.equal(citationChunkLabel(0), 'Chunk 1');
  assert.equal(citationChunkLabel(undefined), null);
});

test('citation PDF links use the topic-scoped API route and page fragment', () => {
  assert.equal(originalPdfUrl('quantum', 'paper1', 3), '/api/topics/quantum/files/paper1/original#page=3');
});
