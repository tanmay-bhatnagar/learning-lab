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
  interrupted?: boolean;
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
export type StreamEvent = {
  type: 'thinking' | 'token' | 'done' | 'error';
  text?: string;
  message?: string;
  model?: string;
  context?: Context;
  retrieval?: MessageRetrieval;
};
