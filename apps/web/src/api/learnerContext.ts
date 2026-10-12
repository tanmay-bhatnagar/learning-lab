import { z } from 'zod';
import { api, json } from './client';
import { conversationLearnerContextPath } from './urls';

const identifierSchema = z.string().regex(/^[a-z0-9][a-z0-9_-]{0,79}$/);
const revisionSchema = z.string().regex(/^[0-9a-f]{64}$/);

export const activeAssessmentFocusSchema = z
  .object({
    file_id: identifierSchema,
    assessment_id: identifierSchema,
    map_revision: revisionSchema,
    section_id: identifierSchema,
    goal: z.string().max(2000),
  })
  .strict();

export const learnerContextSchema = z
  .object({
    schema_version: z.literal(1),
    revision: z.number().int().nonnegative(),
    include_cv: z.boolean(),
    active_assessment: activeAssessmentFocusSchema.nullable(),
  })
  .strict();
export type LearnerContext = z.infer<typeof learnerContextSchema>;

export const learnerContextUpdateSchema = z
  .object({
    expected_revision: z.number().int().nonnegative(),
    include_cv: z.boolean(),
  })
  .strict();
export type LearnerContextUpdate = z.infer<typeof learnerContextUpdateSchema>;

export function getLearnerContext(topicId: string, conversationId: string, signal?: AbortSignal) {
  const path = conversationLearnerContextPath(topicId, conversationId);
  return api(path, learnerContextSchema, signal ? { signal } : {});
}

export async function updateLearnerContext(
  topicId: string,
  conversationId: string,
  input: LearnerContextUpdate,
  signal?: AbortSignal,
): Promise<LearnerContext> {
  const checked = learnerContextUpdateSchema.parse(input);
  const updated = await api(conversationLearnerContextPath(topicId, conversationId), learnerContextSchema, {
    ...json(checked, 'PATCH'),
    ...(signal ? { signal } : {}),
  });
  if (updated.revision !== checked.expected_revision + 1) {
    throw new Error('The server returned an unexpected learner-context revision. Reload and retry.');
  }
  return updated;
}
