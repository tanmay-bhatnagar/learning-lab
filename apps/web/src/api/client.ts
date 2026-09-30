import { z } from 'zod';
import { formatParseError, parsePayload, streamEventSchema, type StreamEvent } from './types';

export function parseErrorDetail(body: unknown, fallback: string): string {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (detail !== undefined) return JSON.stringify(detail);
  }
  return fallback;
}

export async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    return parseErrorDetail(await response.json(), fallback);
  } catch {
    /* keep HTTP status fallback */
    return fallback;
  }
}

export const json = (body: unknown, method = 'POST'): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export async function api<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `Request failed (${response.status})`));
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    /* non-JSON success bodies are treated as protocol errors */
    throw new Error(`Invalid response from ${path}: body is not JSON`);
  }
  return parsePayload(schema, body, path);
}

export async function stream(path: string, body: unknown, signal: AbortSignal, onEvent: (event: StreamEvent) => void) {
  const response = await fetch(`/api${path}`, { ...json(body), signal });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `Chat failed (${response.status})`));
  }
  if (!response.body) throw new Error('The server returned no response stream.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let done = false;
  const consume = (line: string) => {
    if (!line.trim()) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      /* malformed NDJSON lines fail the turn visibly */
      throw new Error('Invalid stream event: line is not JSON');
    }
    const result = streamEventSchema.safeParse(parsed);
    if (!result.success) {
      throw new Error(formatParseError('stream event', result.error));
    }
    const event = result.data;
    if (event.type === 'error') throw new Error(event.message || 'The model could not complete this response.');
    onEvent(event);
    if (event.type === 'done') done = true;
  };
  try {
    while (!done) {
      const part = await reader.read();
      buffer += decoder.decode(part.value, { stream: !part.done });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      lines.forEach(consume);
      if (part.done) {
        consume(buffer);
        break;
      }
    }
    if (!done) throw new Error('Connection ended before the response completed.');
  } finally {
    await reader.cancel().catch(() => {
      /* reader may already be closed after abort */
    });
    reader.releaseLock();
  }
}
