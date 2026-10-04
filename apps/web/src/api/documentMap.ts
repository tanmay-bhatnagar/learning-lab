import { z } from 'zod';

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
    latest_attempt: z.record(z.string(), z.unknown()).nullable().optional(),
    last_summary: z.record(z.string(), z.unknown()).nullable().optional(),
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
  latest_attempt?: Record<string, unknown> | null;
  last_summary?: Record<string, unknown> | null;
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
