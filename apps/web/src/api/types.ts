import { z } from 'zod';

// Schemas accept every shape the backend writes, including older stored records.
// Python writes absent values as null, so optional fields are nullish.

export const fileStatusSchema = z.union([z.enum(['processing', 'ready', 'error']), z.string()]);
export type FileStatus = z.infer<typeof fileStatusSchema>;

export const indexStatusSchema = z.union([z.enum(['ready', 'error', 'not_indexed']), z.string()]);
export type IndexStatus = z.infer<typeof indexStatusSchema>;

export const extractionDiagnosticStatusSchema = z.enum(['confirmed_failure', 'suspected_limitation', 'unassessed']);
export type ExtractionDiagnosticStatus = z.infer<typeof extractionDiagnosticStatusSchema>;

export const retrievalTraceModeSchema = z.enum(['keyword', 'hybrid', 'fallback', 'none']);
export type RetrievalTraceMode = z.infer<typeof retrievalTraceModeSchema>;

export const thinkingTypeSchema = z.enum(['none', 'toggle', 'always', 'levels']);

export const traceComponentSchema = z.looseObject({
  rank: z.number().nullable(),
  score: z.number().nullable(),
  cosine: z.number().nullish(),
});
export type TraceComponent = z.infer<typeof traceComponentSchema>;

export const topicSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  learning_goal: z.string().nullish(),
});
export type Topic = z.infer<typeof topicSchema>;

export const topicsResponseSchema = z.looseObject({
  topics: z.array(topicSchema),
});

export const labAssetSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  page: z.number().nullish(),
  caption: z.string().nullish(),
  bbox: z.unknown().nullish(),
  doc_ref: z.string().nullish(),
});
export type LabAsset = z.infer<typeof labAssetSchema>;

export const extractionDiagnosticsSchema = z.looseObject({
  status: extractionDiagnosticStatusSchema,
  note: z.string(),
  findings: z.array(z.string()),
});

export const labFileSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  status: fileStatusSchema,
  parser: z.string(),
  markdown_name: z.string().nullish(),
  docling_name: z.string().nullish(),
  chunks_name: z.string().nullish(),
  parse_name: z.string().nullish(),
  index_status: indexStatusSchema.nullish(),
  index_mode: z.string().nullish(),
  asset_count: z.number().nullish(),
  page_count: z.number().nullish(),
  assets: z.array(labAssetSchema).nullish(),
  warnings: z.array(z.string()).nullish(),
  extraction_diagnostics: extractionDiagnosticsSchema.nullish(),
  error: z.string().nullish(),
  interrupted: z.boolean().nullish(),
});
export type LabFile = z.infer<typeof labFileSchema>;

export const filesResponseSchema = z.looseObject({
  files: z.array(labFileSchema),
});

export const fileChunkSchema = z.looseObject({
  chunk_id: z.string().nullish(),
  index: z.number().nullish(),
  text: z.string().nullish(),
  contextualized_text: z.string().nullish(),
  headings: z.array(z.string()).nullish(),
  pages: z.array(z.number()).nullish(),
  bboxes: z.array(z.unknown()).nullish(),
  asset_names: z.array(z.string()).nullish(),
  kind: z.string().nullish(),
});
export type FileChunk = z.infer<typeof fileChunkSchema>;

export const fileChunksResponseSchema = z.looseObject({
  chunks: z.array(fileChunkSchema),
});

export const retrievalTraceHitSchema = z.looseObject({
  chunk_id: z.string(),
  file_id: z.string(),
  file_name: z.string(),
  chunk_index: z.number(),
  text: z.string(),
  headings: z.array(z.string()),
  pages: z.array(z.number()),
  bboxes: z.array(z.unknown()),
  asset_ids: z.array(z.string()),
  trace: z.looseObject({
    keyword: traceComponentSchema,
    embedding: traceComponentSchema,
    fusion: traceComponentSchema,
  }),
});
export type RetrievalTraceHit = z.infer<typeof retrievalTraceHitSchema>;

export const retrievalTraceResponseSchema = z.looseObject({
  query: z.string(),
  hits: z.array(retrievalTraceHitSchema),
  mode: retrievalTraceModeSchema,
  warning: z.string().nullish(),
});
export type RetrievalTraceResponse = z.infer<typeof retrievalTraceResponseSchema>;

export const retrievalTraceRequestSchema = z.looseObject({
  query: z.string(),
  file_ids: z.array(z.string()),
  top_k: z.number(),
});
export type RetrievalTraceRequest = z.infer<typeof retrievalTraceRequestSchema>;

export const citationSchema = z.looseObject({
  chunk_id: z.string(),
  file_id: z.string(),
  file_name: z.string(),
  headings: z.array(z.string()),
  pages: z.array(z.number()),
  bboxes: z.array(z.unknown()),
  assets: z.array(z.string()),
  text: z.string().nullish(),
  chunk_index: z.number().nullish(),
});
export type Citation = z.infer<typeof citationSchema>;

export const messageRetrievalSchema = z.looseObject({
  mode: retrievalTraceModeSchema,
  warning: z.string().nullish(),
  citations: z.array(citationSchema),
});
export type MessageRetrieval = z.infer<typeof messageRetrievalSchema>;

export const messageSchema = z.looseObject({
  role: z.string(),
  content: z.string(),
  thinking: z.string().nullish(),
  model: z.string().nullish(),
  incomplete: z.boolean().nullish(),
  retrieval: messageRetrievalSchema.nullish(),
});
export type Message = z.infer<typeof messageSchema>;

export const contextSchema = z.looseObject({
  used: z.number().nullish(),
  limit: z.number().nullish(),
  estimated: z.boolean().nullish(),
  truncated_messages: z.number().nullish(),
});
export type Context = z.infer<typeof contextSchema>;

export const messagesResponseSchema = z.looseObject({
  messages: z.array(messageSchema),
  context: contextSchema.nullish(),
});

export const modelSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  display_name: z.string().nullish(),
  max_context_length: z.number().nullish(),
  size_bytes: z.number().nullish(),
  quantization: z.string().nullish(),
  parameter_size: z.string().nullish(),
  vision: z.boolean().nullish(),
  thinking: z.looseObject({
    type: thinkingTypeSchema,
    levels: z.array(z.string()).nullish(),
  }),
});
export type Model = z.infer<typeof modelSchema>;

export const modelsResponseSchema = z.looseObject({
  models: z.array(modelSchema),
  error: z.string().nullish(),
});

export const settingsSchema = z.looseObject({
  model: z.string(),
  context_limit: z.number(),
  parser: z.string(),
  embedding_model: z.string(),
  retrieval_top_k: z.number(),
});
export type Settings = z.infer<typeof settingsSchema>;

export const learningGoalResponseSchema = z.looseObject({
  learning_goal: z.string(),
});

export const markdownResponseSchema = z.looseObject({
  markdown: z.string(),
});

export const streamEventSchema = z.discriminatedUnion('type', [
  z.looseObject({ type: z.literal('thinking'), text: z.string().nullish() }),
  z.looseObject({ type: z.literal('token'), text: z.string().nullish() }),
  z.looseObject({
    type: z.literal('done'),
    context: contextSchema.nullish(),
    retrieval: messageRetrievalSchema.nullish(),
    model: z.string().nullish(),
  }),
  z.looseObject({ type: z.literal('error'), message: z.string().nullish() }),
]);
export type StreamEvent = z.infer<typeof streamEventSchema>;

export const thinkingPrefsSchema = z.record(z.string(), z.union([z.boolean(), z.string()]));
export type ThinkingPrefs = z.infer<typeof thinkingPrefsSchema>;

export function formatParseError(label: string, error: z.ZodError): string {
  const detail = error.issues.map((issue) => issue.message).join('; ');
  return `Invalid ${label}: ${detail}`;
}

export function parsePayload<T>(schema: z.ZodType<T>, body: unknown, label: string): T {
  const result = schema.safeParse(body);
  if (!result.success) throw new Error(formatParseError(label, result.error));
  return result.data;
}
