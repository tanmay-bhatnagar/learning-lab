import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';

async function load(name) {
  const source = await fs.readFile(new URL(`../src/${name}.ts`, import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
}

const { citationChunkLabel, citationLocation, hasSources, modeBadgeLabel, sourcesButtonLabel, sourcesCount } =
  await load('citationsHelpers');
const { originalPdfUrl } = await load('api');

test('sources helpers count citations and build button labels', () => {
  const retrieval = { mode: 'keyword', citations: [{ chunk_id: 'a' }, { chunk_id: 'b' }] };
  assert.equal(sourcesCount(undefined), 0);
  assert.equal(sourcesCount(retrieval), 2);
  assert.equal(hasSources(retrieval), true);
  assert.equal(hasSources({ mode: 'none', citations: [] }), false);
  assert.equal(hasSources({ mode: 'fallback', citations: [], warning: 'No matches were available.' }), true);
  assert.equal(sourcesButtonLabel(3), 'Sources (3)');
});

test('citation labels expose mode badges, locations, and chunk numbers', () => {
  assert.equal(modeBadgeLabel('hybrid'), 'Hybrid (keyword + embeddings + RRF)');
  assert.equal(modeBadgeLabel('none'), 'No retrieval');
  assert.equal(citationLocation('paper.pdf', ['Intro', 'Setup'], [2, 3]), 'paper.pdf · Intro › Setup · Pages 2, 3');
  assert.equal(citationChunkLabel(0), 'Chunk 1');
  assert.equal(citationChunkLabel(undefined), null);
});

test('citation PDF links use the topic-scoped API route and page fragment', () => {
  assert.equal(originalPdfUrl('quantum', 'paper1', 3), '/api/topics/quantum/files/paper1/original#page=3');
});
