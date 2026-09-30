import { z } from 'zod';

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
  cosine: z.number().nullable().optional(),
});
export type TraceComponent = z.infer<typeof traceComponentSchema>;

export const topicSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  learning_goal: z.string().optional(),
});
export type Topic = z.infer<typeof topicSchema>;

export const topicsResponseSchema = z.looseObject({
  topics: z.array(topicSchema),
});

export const labAssetSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  page: z.number().optional(),
  caption: z.string().optional(),
  bbox: z.unknown().optional(),
  doc_ref: z.string().optional(),
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
  markdown_name: z.string().optional(),
  docling_name: z.string().optional(),
  chunks_name: z.string().optional(),
  parse_name: z.string().optional(),
  index_status: indexStatusSchema.optional(),
  index_mode: z.string().optional(),
  asset_count: z.number().optional(),
  page_count: z.number().optional(),
  assets: z.array(labAssetSchema).optional(),
  warnings: z.array(z.string()).optional(),
  extraction_diagnostics: extractionDiagnosticsSchema.optional(),
  error: z.string().optional(),
  interrupted: z.boolean().optional(),
});
export type LabFile = z.infer<typeof labFileSchema>;

export const filesResponseSchema = z.looseObject({
  files: z.array(labFileSchema),
});

export const fileChunkSchema = z.looseObject({
  chunk_id: z.string().optional(),
  index: z.number().optional(),
  text: z.string().optional(),
  contextualized_text: z.string().optional(),
  headings: z.array(z.string()).optional(),
  pages: z.array(z.number()).optional(),
  bboxes: z.array(z.unknown()).optional(),
  asset_names: z.array(z.string()).optional(),
  kind: z.string().optional(),
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
  warning: z.string().optional(),
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
  trace: z.looseObject({
    keyword: traceComponentSchema,
    embedding: traceComponentSchema,
    fusion: traceComponentSchema,
  }),
  text: z.string().optional(),
  chunk_index: z.number().optional(),
});
export type Citation = z.infer<typeof citationSchema>;

export const messageRetrievalSchema = z.looseObject({
  mode: retrievalTraceModeSchema,
  warning: z.string().optional(),
  citations: z.array(citationSchema),
});
export type MessageRetrieval = z.infer<typeof messageRetrievalSchema>;

export const messageSchema = z.looseObject({
  role: z.string(),
  content: z.string(),
  thinking: z.string().optional(),
  model: z.string().optional(),
  incomplete: z.boolean().optional(),
  retrieval: messageRetrievalSchema.optional(),
});
export type Message = z.infer<typeof messageSchema>;

export const contextSchema = z.looseObject({
  used: z.number().optional(),
  limit: z.number().optional(),
  estimated: z.boolean().optional(),
  truncated_messages: z.number().optional(),
});
export type Context = z.infer<typeof contextSchema>;

export const messagesResponseSchema = z.looseObject({
  messages: z.array(messageSchema),
  context: contextSchema.optional(),
});

export const modelSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  display_name: z.string().optional(),
  max_context_length: z.number().optional(),
  size_bytes: z.number().optional(),
  quantization: z.string().optional(),
  parameter_size: z.string().optional(),
  vision: z.boolean().optional(),
  thinking: z.looseObject({
    type: thinkingTypeSchema,
    levels: z.array(z.string()).optional(),
  }),
});
export type Model = z.infer<typeof modelSchema>;

export const modelsResponseSchema = z.looseObject({
  models: z.array(modelSchema),
  error: z.string().optional(),
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
  z.looseObject({ type: z.literal('thinking'), text: z.string().optional() }),
  z.looseObject({ type: z.literal('token'), text: z.string().optional() }),
  z.looseObject({
    type: z.literal('done'),
    context: contextSchema.optional(),
    retrieval: messageRetrievalSchema.optional(),
    model: z.string().optional(),
  }),
  z.looseObject({ type: z.literal('error'), message: z.string().optional() }),
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
