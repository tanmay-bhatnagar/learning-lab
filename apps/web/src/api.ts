export type Topic = { id: string; name: string; learning_goal?: string };
export type LabAsset = {
  id: string;
  name: string;
  kind: string;
  page?: number;
  caption?: string;
  bbox?: unknown;
  doc_ref?: string;
};
export type LabFile = {
  id: string;
  name: string;
  status: string;
  parser: string;
  markdown_name?: string;
  docling_name?: string;
  chunks_name?: string;
  parse_name?: string;
  index_status?: string;
  index_mode?: string;
  asset_count?: number;
  page_count?: number;
  assets?: LabAsset[];
  warnings?: string[];
  extraction_diagnostics?: {
    status: 'confirmed_failure' | 'suspected_limitation' | 'unassessed';
    note: string;
    findings: string[];
  };
  error?: string;
};
export type FileChunk = {
  chunk_id?: string;
  index?: number;
  text?: string;
  contextualized_text?: string;
  headings?: string[];
  pages?: number[];
  bboxes?: unknown[];
  asset_names?: string[];
  kind?: string;
};
export type TraceComponent = { rank: number | null; score: number | null; cosine?: number | null };
export type RetrievalTraceHit = {
  chunk_id: string;
  file_id: string;
  file_name: string;
  chunk_index: number;
  text: string;
  headings: string[];
  pages: number[];
  bboxes: unknown[];
  asset_ids: string[];
  trace: { keyword: TraceComponent; embedding: TraceComponent; fusion: TraceComponent };
};
export type RetrievalTraceMode = 'keyword' | 'hybrid' | 'fallback' | 'none';
export type RetrievalTraceResponse = {
  query: string;
  hits: RetrievalTraceHit[];
  mode: RetrievalTraceMode;
  warning?: string;
};
export type RetrievalTraceRequest = { query: string; file_ids: string[]; top_k: number };
export type Citation = {
  chunk_id: string;
  file_id: string;
  file_name: string;
  headings: string[];
  pages: number[];
  bboxes: unknown[];
  assets: string[];
  trace: { keyword: TraceComponent; embedding: TraceComponent; fusion: TraceComponent };
  text?: string;
  chunk_index?: number;
};
export type MessageRetrieval = { mode: RetrievalTraceMode; warning?: string; citations: Citation[] };
export type Message = {
  role: string;
  content: string;
  thinking?: string;
  model?: string;
  incomplete?: boolean;
  retrieval?: MessageRetrieval;
};
export type Context = { used?: number; limit?: number; estimated?: boolean; truncated_messages?: number };
export type Model = {
  id: string;
  name: string;
  display_name?: string;
  max_context_length?: number;
  size_bytes?: number;
  quantization?: string;
  parameter_size?: string;
  vision?: boolean;
  thinking: { type: 'none' | 'toggle' | 'always' | 'levels'; levels?: string[] };
};
export type Settings = {
  model: string;
  context_limit: number;
  parser: string;
  embedding_model: string;
  retrieval_top_k: number;
};
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep HTTP status */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}
export const json = (body: unknown, method = 'POST'): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});
export const topicPath = (id: string) => `/topics/${encodeURIComponent(id)}`;
export const filePath = (topic: string, fileId: string) => `${topicPath(topic)}/files/${encodeURIComponent(fileId)}`;
export const originalPdfUrl = (topic: string, fileId: string, page: number) =>
  `/api${filePath(topic, fileId)}/original#page=${page}`;
export const fileChunksPath = (topic: string, fileId: string) => `${filePath(topic, fileId)}/chunks`;
export const fileAssetPath = (topic: string, fileId: string, assetId: string) =>
  `${filePath(topic, fileId)}/assets/${encodeURIComponent(assetId)}`;
export const retrievalTracePath = (topic: string) => `${topicPath(topic)}/retrieval/trace`;
export type StreamEvent = {
  type: 'thinking' | 'token' | 'done' | 'error';
  text?: string;
  message?: string;
  model?: string;
  context?: Context;
  retrieval?: MessageRetrieval;
};
export async function stream(path: string, body: unknown, signal: AbortSignal, onEvent: (event: StreamEvent) => void) {
  const response = await fetch(`/api${path}`, { ...json(body), signal });
  if (!response.ok) {
    let message = `Chat failed (${response.status})`;
    try {
      const data = await response.json();
      message = typeof data.detail === 'string' ? data.detail : message;
    } catch {}
    throw new Error(message);
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
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
