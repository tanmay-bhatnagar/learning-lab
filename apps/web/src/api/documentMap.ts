import { z } from 'zod';
import { readErrorDetail } from './client';
import { formatParseError, messageSchema, summaryImportMetadataSchema } from './types';

export const mapSourceUnitSchema = z.object({
  id: z.string(),
  source_ref: z.string(),
  source_refs: z.array(z.string()),
  kind: z.string(),
  content_layer: z.string(),
  text: z.string(),
  pages: z.array(z.number()),
  included: z.boolean(),
  warnings: z.array(z.string()),
});
export type MapSourceUnit = z.infer<typeof mapSourceUnitSchema>;

export const mapSectionSchema: z.ZodType<MapSection> = z.lazy(() =>
  z.object({
    id: z.string(),
    source_ref: z.string(),
    title: z.string(),
    level: z.number(),
    pages: z.array(z.number()),
    text: z.string(),
    direct_unit_ids: z.array(z.string()),
    source_unit_ids: z.array(z.string()),
    children: z.array(mapSectionSchema),
    latest_attempt: summaryAttemptSchema.nullish(),
    last_summary: savedSummarySchema.nullish(),
  }),
);

export type MapSection = {
  id: string;
  source_ref: string;
  title: string;
  level: number;
  pages: number[];
  text: string;
  direct_unit_ids: string[];
  source_unit_ids: string[];
  children: MapSection[];
  latest_attempt?: SummaryAttempt | null;
  last_summary?: SavedSummary | null;
};

export const documentMapSchema = z.object({
  schema_version: z.number(),
  builder_version: z.string(),
  file_id: z.string(),
  revision: z.string(),
  source_revision: z.object({ pdf_sha256: z.string(), docling_sha256: z.string() }),
  outline_mode: z.enum(['headings', 'pages']),
  sections: z.array(mapSectionSchema),
  units: z.array(mapSourceUnitSchema),
  coverage: z.object({
    total_units: z.number(),
    included_units: z.number(),
    excluded_units: z.number(),
    accounted_units: z.number(),
    total_source_items: z.number(),
    accounted_source_items: z.number(),
  }),
  warnings: z.array(z.string()),
  history: z.array(z.unknown()),
});
export type DocumentMap = z.infer<typeof documentMapSchema>;

export const documentMapResponseSchema = z.discriminatedUnion('status', [
  z.object({ status: z.literal('not_built'), map: z.null() }),
  z.object({ status: z.enum(['ready', 'stale']), map: documentMapSchema }),
]);
export type DocumentMapResponse = z.infer<typeof documentMapResponseSchema>;

export const mapSectionResponseSchema = z.object({
  status: z.enum(['ready', 'stale']),
  section: mapSectionSchema,
  source_units: z.array(mapSourceUnitSchema),
});

export const summarySourceSchema = z.object({
  label: z.string().regex(/^S[1-9][0-9]*$/),
  unit_id: z.string().min(1),
  source_refs: z.array(z.string()).min(1),
  pages: z.array(z.number().int().positive()),
});
export type SummarySource = z.infer<typeof summarySourceSchema>;

export const summaryAttemptSchema = z.object({
  id: z.string().min(1),
  revision: z.string().regex(/^[0-9a-f]{64}$/),
  section_id: z.string().min(1),
  status: z.enum(['generating', 'completed', 'cancelled', 'error', 'interrupted']),
  started_at: z.string(),
  finished_at: z.string().nullable(),
  model: z.string().min(1),
  actual_model: z.string().min(1).nullable().optional(),
  context_limit: z.number().int().min(1024).max(32768),
  think: z.union([z.boolean(), z.enum(['low', 'medium', 'high'])]).nullable(),
  policy_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  prompt_version: z.literal('section-summary-v1'),
  source_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  prompt_context: z.record(z.string(), z.union([z.number(), z.boolean()])),
  content: z.string(),
  error: z.string().nullable(),
});
export type SummaryAttempt = z.infer<typeof summaryAttemptSchema>;

export const savedSummarySchema = z.object({
  id: z.string().min(1),
  revision: z.string().regex(/^[0-9a-f]{64}$/),
  section_id: z.string().min(1),
  section_title: z.string(),
  content: z.string().min(1),
  model: z.string().min(1),
  created_at: z.string(),
  policy_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  prompt_version: z.literal('section-summary-v1'),
  source_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  sources: z.array(summarySourceSchema).min(1),
  context_limit: z.number().int().min(1024).max(32768),
  think: z.union([z.boolean(), z.enum(['low', 'medium', 'high'])]).nullable(),
});
export type SavedSummary = z.infer<typeof savedSummarySchema>;

export { summaryImportMetadataSchema } from './types';
export type SummaryImportMetadata = z.infer<typeof summaryImportMetadataSchema>;

export const summaryImportMessageSchema = messageSchema.extend({
  role: z.literal('user'),
  summary_import: summaryImportMetadataSchema,
});

export const summaryImportResponseSchema = z.object({
  conversation_id: z.string(),
  imported: z.boolean(),
  message: summaryImportMessageSchema,
  messages: z.array(messageSchema),
  context: z.record(z.string(), z.unknown()).optional(),
});
export type SummaryImportResponse = z.infer<typeof summaryImportResponseSchema>;

export const summaryStreamEventSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('started'),
    attempt_id: z.string(),
    revision: z.string(),
    section_id: z.string(),
    attempt: summaryAttemptSchema,
  }),
  z.object({ type: z.literal('token'), attempt_id: z.string(), text: z.string() }),
  z.object({ type: z.literal('thinking'), attempt_id: z.string(), text: z.string() }),
  z.object({
    type: z.literal('done'),
    attempt_id: z.string(),
    summary: savedSummarySchema,
    attempt: summaryAttemptSchema,
  }),
  z.object({
    type: z.literal('error'),
    attempt_id: z.string(),
    message: z.string(),
    attempt: summaryAttemptSchema.optional(),
  }),
]);
export type SummaryStreamEvent = z.infer<typeof summaryStreamEventSchema>;

export async function streamDocumentSummary(
  path: string,
  body: unknown,
  signal: AbortSignal,
  onEvent: (event: SummaryStreamEvent) => void,
  onAccepted: () => void = () => {},
): Promise<void> {
  const response = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw new Error(await readErrorDetail(response, `Summary request failed (${response.status})`));
  onAccepted();
  if (!response.body) throw new Error('The server returned no summary stream.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let terminal = false;
  const consume = (line: string) => {
    if (!line.trim()) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch (error) {
      throw new Error('Invalid summary event: line is not JSON.', { cause: error });
    }
    const result = summaryStreamEventSchema.safeParse(parsed);
    if (!result.success) throw new Error(formatParseError('summary event', result.error));
    const event = result.data;
    onEvent(event);
    if (event.type === 'done' || event.type === 'error') terminal = true;
  };
  try {
    while (!terminal) {
      const part = await reader.read();
      buffer += decoder.decode(part.value, { stream: !part.done });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        consume(line);
        if (terminal) break;
      }
      if (part.done) {
        if (!terminal) consume(buffer);
        break;
      }
    }
    if (!terminal) throw new Error('Connection ended before the summary completed.');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
