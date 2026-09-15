import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';
const source = await fs.readFile(new URL('../src/api.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { stream } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
function response(chunks) { const encoder = new TextEncoder(); return new Response(new ReadableStream({ start(controller) { for (const chunk of chunks) controller.enqueue(encoder.encode(chunk)); controller.close(); } })); }
test('NDJSON handles split records, blank lines, thinking, and final record without newline', async () => {
  globalThis.fetch = async () => response(['{"type":"thinking","te', 'xt":"consider"}\n\n{"type":"token","text":"answer"}\n', '{"type":"done","context":{"used":123,"limit":8192}}']);
  const events = []; await stream('/chat', {}, new AbortController().signal, e => events.push(e));
  assert.deepEqual(events.map(e => e.type), ['thinking', 'token', 'done']); assert.equal(events[2].context.used, 123);
});
test('premature EOF is an error and preserves delivered tokens', async () => {
  globalThis.fetch = async () => response(['{"type":"token","text":"partial"}\n']);
  const events = []; await assert.rejects(stream('/chat', {}, new AbortController().signal, e => events.push(e)), /before the response completed/); assert.equal(events[0].text, 'partial');
});
test('server stream errors surface the actual message', async () => {
  globalThis.fetch = async () => response(['{"type":"error","message":"Model unavailable"}\n']);
  await assert.rejects(stream('/chat', {}, new AbortController().signal, () => {}), /Model unavailable/);
});
test('HTTP errors surface API detail', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Topic missing' }), { status: 404 });
  await assert.rejects(stream('/chat', {}, new AbortController().signal, () => {}), /Topic missing/);
});
test('done event preserves actual model metadata for assistant attribution', async () => {
  globalThis.fetch = async () => response(['{"type":"token","text":"answer"}\n{"type":"done","model":"qwen3.5:9b-q4_K_M","context":{"limit":32768}}']);
  const events = []; await stream('/chat', {}, new AbortController().signal, e => events.push(e));
  assert.equal(events.at(-1).model, 'qwen3.5:9b-q4_K_M');
});
