export type Topic = { id: string; name: string };
export type LabFile = { id: string; name: string; status: string; parser: string; markdown_name?: string; error?: string };
export type Message = { role: string; content: string; thinking?: string; incomplete?: boolean };
export type Context = { used?: number; limit?: number; estimated?: boolean; truncated_messages?: number };
export type Model = { id: string; name: string; size_bytes?: number; quantization?: string; parameter_size?: string; thinking: { type: 'none' | 'toggle' | 'always' | 'levels'; levels?: string[] } };
export type Settings = { model: string; context_limit: number; parser: string };
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body); } catch { /* keep HTTP status */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}
export const json = (body: unknown, method = 'POST'): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export const topicPath = (id: string) => `/topics/${encodeURIComponent(id)}`;
export type StreamEvent = { type: 'thinking' | 'token' | 'done' | 'error'; text?: string; message?: string; context?: Context };
export async function stream(path: string, body: unknown, signal: AbortSignal, onEvent: (event: StreamEvent) => void) {
  const response = await fetch(`/api${path}`, { ...json(body), signal });
  if (!response.ok) { let message = `Chat failed (${response.status})`; try { const data = await response.json(); message = typeof data.detail === 'string' ? data.detail : message; } catch {} throw new Error(message); }
  if (!response.body) throw new Error('The server returned no response stream.');
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let done = false;
  const consume = (line: string) => { if (!line.trim()) return; const event = JSON.parse(line) as StreamEvent; if (event.type === 'error') throw new Error(event.message || 'The model could not complete this response.'); onEvent(event); if (event.type === 'done') done = true; };
  try { while (!done) { const part = await reader.read(); buffer += decoder.decode(part.value, { stream: !part.done }); const lines = buffer.split('\n'); buffer = lines.pop() ?? ''; lines.forEach(consume); if (part.done) { consume(buffer); break; } } if (!done) throw new Error('Connection ended before the response completed.'); }
  finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
