import { z } from 'zod';
import { api, json } from './client';

const recordIdSchema = z.string().regex(/^[a-f0-9]{32}$/);
const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);
const comfortSchema = z.enum(['comfortable', 'refresher', 'new', 'unsure']);
const parserSchema = z.enum(['docling', 'markitdown', 'anydoc']);

export const cvDiagnosticsSchema = z
  .object({
    status: z.enum(['ready', 'error']),
    findings: z.array(z.string()),
    note: z.string().nullish(),
  })
  .strict();

export const profileCvSchema = z
  .object({
    id: recordIdSchema,
    original_name: z.string().min(1),
    status: z.enum(['ready', 'error']),
    revoked: z.boolean(),
    parser: z.string().min(1).nullish(),
    parser_version: z.string().nullish(),
    original_sha256: sha256Schema,
    extracted_sha256: sha256Schema.nullable(),
    native_document_sha256: sha256Schema.nullish(),
    extraction_diagnostics: cvDiagnosticsSchema,
    created_at: z.string().min(1),
  })
  .strict()
  .superRefine((cv, context) => {
    if (cv.status === 'ready' && !cv.extracted_sha256) {
      context.addIssue({
        code: 'custom',
        path: ['extracted_sha256'],
        message: 'Ready CV needs extracted-text identity.',
      });
    }
    if (cv.status === 'error' && cv.extracted_sha256 !== null) {
      context.addIssue({
        code: 'custom',
        path: ['extracted_sha256'],
        message: 'Failed CV cannot have extracted-text identity.',
      });
    }
  });
export type ProfileCv = z.infer<typeof profileCvSchema>;

export const profileSchema = z
  .object({
    schema_version: z.literal(1),
    revision: z.number().int().nonnegative(),
    active_cv_id: recordIdSchema.nullable(),
    cvs: z.array(profileCvSchema),
  })
  .strict()
  .superRefine((profile, context) => {
    if (!profile.active_cv_id) return;
    const active = profile.cvs.find((cv) => cv.id === profile.active_cv_id);
    if (!active || active.status !== 'ready' || active.revoked) {
      context.addIssue({
        code: 'custom',
        path: ['active_cv_id'],
        message: 'Active CV must be available and extracted.',
      });
    }
  });
export type Profile = z.infer<typeof profileSchema>;

const proficiencyCommonSchema = z.object({
  id: recordIdSchema,
  concept: z.string().min(1),
  notes: z.string().nullish(),
});

export const manualProficiencyEntrySchema = proficiencyCommonSchema
  .extend({
    comfort: comfortSchema,
    source_kind: z.literal('user_manual'),
    updated_at: z.string().nullish(),
  })
  .strict();

export const modelRequirementEntrySchema = proficiencyCommonSchema
  .extend({
    comfort: comfortSchema.nullable(),
    source_kind: z.literal('model_requirement'),
    topic_id: z.string().min(1),
    assessment_id: z.string().min(1),
    requirement_id: z.string().min(1),
    updated_at: z.string().nullish(),
  })
  .strict();

export const proficiencyEntrySchema = z.discriminatedUnion('source_kind', [
  manualProficiencyEntrySchema,
  modelRequirementEntrySchema,
]);
export type ProficiencyEntry = z.infer<typeof proficiencyEntrySchema>;

export const proficiencySchema = z
  .object({
    schema_version: z.literal(1),
    revision: z.number().int().nonnegative(),
    entries: z.array(proficiencyEntrySchema),
  })
  .strict();
export type ProficiencyState = z.infer<typeof proficiencySchema>;

export const cvUploadResponseSchema = profileCvSchema.extend({ revision: z.number().int().nonnegative() }).strict();
export type CvUploadResponse = z.infer<typeof cvUploadResponseSchema>;

export const cvTextSchema = z
  .object({
    id: recordIdSchema,
    original_name: z.string().min(1),
    parser: z.string().min(1),
    parser_version: z.string(),
    text: z.string(),
  })
  .strict();
export type CvText = z.infer<typeof cvTextSchema>;

export type ProfileRevisionInput = { expected_revision: number };

export type ProficiencyCreateInput = {
  concept: string;
  comfort: z.infer<typeof comfortSchema>;
  notes: string;
  expected_revision: number;
};

export type ProficiencyUpdateInput = {
  concept?: string;
  comfort?: z.infer<typeof comfortSchema>;
  notes?: string;
  expected_revision: number;
};

export type ProficiencyBatchInput = ProfileRevisionInput & {
  additions: Array<{ concept: string; comfort: z.infer<typeof comfortSchema>; notes: string }>;
  updates: Array<{
    id: string;
    concept?: string;
    comfort?: z.infer<typeof comfortSchema> | null;
    notes?: string;
  }>;
};

const profileRequest = (signal?: AbortSignal): RequestInit => (signal ? { signal } : {});

export function getProfile(signal?: AbortSignal): Promise<Profile> {
  return api('/profile', profileSchema, profileRequest(signal));
}

export function getProficiency(signal?: AbortSignal): Promise<ProficiencyState> {
  return api('/profile/proficiency', proficiencySchema, profileRequest(signal));
}

export function saveProficiencyBatch(input: ProficiencyBatchInput, signal?: AbortSignal): Promise<ProficiencyState> {
  return api('/profile/proficiency', proficiencySchema, {
    ...json(input, 'PUT'),
    ...profileRequest(signal),
  });
}

export function uploadCv(
  file: File,
  originalName: string,
  parser: z.infer<typeof parserSchema> = 'docling',
  signal?: AbortSignal,
) {
  const body = new FormData();
  body.append('file', file, file.name);
  body.append('original_name', originalName);
  body.append('parser', parserSchema.parse(parser));
  return api('/profile/cvs', cvUploadResponseSchema, { method: 'POST', body, ...(signal ? { signal } : {}) });
}

export function getCvText(cvId: string, signal?: AbortSignal): Promise<CvText> {
  return api(`/profile/cvs/${encodeURIComponent(cvId)}/text`, cvTextSchema, profileRequest(signal));
}

export function cvOriginalUrl(cvId: string): string {
  return `/api/profile/cvs/${encodeURIComponent(cvId)}/original`;
}

export function selectCv(cvId: string, expectedRevision: number, signal?: AbortSignal): Promise<Profile> {
  return api(`/profile/cvs/${encodeURIComponent(cvId)}/select`, profileSchema, {
    ...json({ expected_revision: expectedRevision }),
    ...profileRequest(signal),
  });
}

export function revokeCv(cvId: string, expectedRevision: number, signal?: AbortSignal): Promise<Profile> {
  return api(`/profile/cvs/${encodeURIComponent(cvId)}/revoke`, profileSchema, {
    ...json({ expected_revision: expectedRevision }),
    ...profileRequest(signal),
  });
}

export function createProficiencyEntry(input: ProficiencyCreateInput, signal?: AbortSignal): Promise<ProficiencyState> {
  return api('/profile/proficiency/entries', proficiencySchema, {
    ...json(input),
    ...profileRequest(signal),
  });
}

export function updateProficiencyEntry(
  entryId: string,
  input: Omit<ProficiencyUpdateInput, 'expected_revision'> & ProfileRevisionInput,
  signal?: AbortSignal,
): Promise<ProficiencyState> {
  return api(`/profile/proficiency/entries/${encodeURIComponent(entryId)}`, proficiencySchema, {
    ...json(input, 'PATCH'),
    ...profileRequest(signal),
  });
}
