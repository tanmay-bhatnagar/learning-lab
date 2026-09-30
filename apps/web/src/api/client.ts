import type { StreamEvent } from './types';

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

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `Request failed (${response.status})`));
  }
  return response.json() as Promise<T>;
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
    const event = JSON.parse(line) as StreamEvent;
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
