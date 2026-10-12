import { z } from 'zod';
import { api, json, readErrorDetail } from './client';
import { learnerContextSchema } from './learnerContext';
import { filePrerequisitesPath, sectionPrerequisitesPath, conversationPrerequisiteImportsPath } from './urls';
import { contextSchema, formatParseError, messageSchema, prerequisiteImportMetadataSchema } from './types';

const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const recordIdSchema = z.string().regex(/^[a-z0-9][a-z0-9_-]{0,79}$/);
const cvIdSchema = z.string().regex(/^[0-9a-f]{32}$/);
const sourceLabelSchema = z.string().regex(/^S[1-9][0-9]*$/);
const timestampSchema = z.string().datetime({ offset: true });

export const prerequisiteSourceSchema = z
  .object({
    label: sourceLabelSchema,
    unit_id: z.string().min(1),
    source_refs: z.array(z.string().min(1)).min(1),
    pages: z.array(z.number().int().positive()),
  })
  .strict();
export type PrerequisiteSource = z.infer<typeof prerequisiteSourceSchema>;

export const prerequisiteRequirementSchema = z
  .object({
    requirement_id: z.string().regex(/^req-[0-9a-f]{24}$/),
    concept: z.string().min(1).max(160),
    reason: z.string().min(1).max(800),
    question: z.string().min(1),
    source_labels: z.array(sourceLabelSchema).min(1),
    cv_background: z.enum(['mentioned', 'not_stated']),
    cv_source_labels: z.array(z.literal('CV1')).max(1),
    cv_quote: z.string().max(1000),
    comfort: z.null(),
    comfort_status: z.literal('pending'),
  })
  .strict()
  .refine((requirement) => requirement.question === `Are you already comfortable with ${requirement.concept}?`, {
    path: ['question'],
    message: 'Requirement question must ask the user about their comfort level.',
  })
  .superRefine((requirement, context) => {
    if (
      requirement.cv_background === 'not_stated' &&
      (requirement.cv_source_labels.length > 0 || requirement.cv_quote)
    ) {
      context.addIssue({
        code: 'custom',
        path: ['cv_source_labels'],
        message: 'Unstated CV background cannot cite CV text.',
      });
    }
    if (
      requirement.cv_background === 'mentioned' &&
      (!requirement.cv_quote.trim() || requirement.cv_source_labels[0] !== 'CV1')
    ) {
      context.addIssue({
        code: 'custom',
        path: ['cv_source_labels'],
        message: 'Mentioned CV background needs its CV citation and quote.',
      });
    }
  });
export type PrerequisiteRequirement = z.infer<typeof prerequisiteRequirementSchema>;

export const prerequisiteAssessmentSchema = z
  .object({
    attempt_id: z.string().min(1).max(100),
    assessment_id: z.string().min(1).max(100),
    topic_id: recordIdSchema,
    file_id: recordIdSchema,
    map_revision: sha256Schema,
    section_id: recordIdSchema,
    cv_id: cvIdSchema,
    cv_text_sha256: sha256Schema,
    source_sha256: sha256Schema,
    overview: z.string().min(1).max(1200),
    requirements: z.array(prerequisiteRequirementSchema).max(8),
    sources: z.array(prerequisiteSourceSchema).min(1),
    finished_at: z.string().datetime({ offset: true }),
  })
  .strict()
  .superRefine((assessment, context) => {
    const labels = new Set(assessment.sources.map((source) => source.label));
    assessment.requirements.forEach((requirement, index) => {
      if (requirement.source_labels.some((label) => !labels.has(label))) {
        context.addIssue({
          code: 'custom',
          path: ['requirements', index, 'source_labels'],
          message: 'Requirement cites a source absent from its assessment.',
        });
      }
    });
  });
export type PrerequisiteAssessment = z.infer<typeof prerequisiteAssessmentSchema>;

export const prerequisiteAttemptSchema = z
  .object({
    id: z.string().min(1).max(100),
    assessment_id: z.string().min(1).max(100),
    topic_id: recordIdSchema,
    file_id: recordIdSchema,
    map_revision: sha256Schema,
    section_id: recordIdSchema,
    status: z.enum(['generating', 'completed', 'cancelled', 'error', 'interrupted']),
    started_at: timestampSchema,
    finished_at: timestampSchema.nullable(),
    provenance: z
      .object({
        prompt_version: z.string().min(1),
        source_sha256: sha256Schema,
        runtime_policy_sha256: sha256Schema,
        cv_id: cvIdSchema,
        cv_text_sha256: sha256Schema,
        goal: z.string().max(2000),
        model: z.string().min(1).max(200),
      })
      .strict(),
    diagnostic: z.string().max(2000).nullable(),
  })
  .strict()
  .superRefine((attempt, context) => {
    if (attempt.status === 'generating' && attempt.finished_at !== null) {
      context.addIssue({ code: 'custom', path: ['finished_at'], message: 'Generating attempts cannot be finished.' });
    }
    if (attempt.status !== 'generating' && attempt.finished_at === null) {
      context.addIssue({ code: 'custom', path: ['finished_at'], message: 'Finished attempts need a finish time.' });
    }
    if (attempt.status === 'generating' && attempt.diagnostic !== null) {
      context.addIssue({
        code: 'custom',
        path: ['diagnostic'],
        message: 'Generating attempts cannot have diagnostics.',
      });
    }
  });
export type PrerequisiteAttempt = z.infer<typeof prerequisiteAttemptSchema>;

export const prerequisiteStateSchema = z
  .object({
    schema_version: z.literal(1),
    topic_id: recordIdSchema,
    file_id: recordIdSchema,
    map_revision: sha256Schema.nullable(),
    selected_cv: z
      .object({ id: cvIdSchema, original_name: z.string().min(1), extracted_sha256: sha256Schema })
      .strict()
      .nullable(),
    attempts: z.array(prerequisiteAttemptSchema),
    assessments: z.array(prerequisiteAssessmentSchema),
    current_assessment: prerequisiteAssessmentSchema.nullable(),
  })
  .strict()
  .superRefine((state, context) => {
    for (const attempt of state.attempts) {
      if (attempt.topic_id !== state.topic_id || attempt.file_id !== state.file_id) {
        context.addIssue({
          code: 'custom',
          path: ['attempts'],
          message: 'Attempt source identity does not match state.',
        });
      }
    }
    for (const assessment of state.assessments) {
      if (assessment.topic_id !== state.topic_id || assessment.file_id !== state.file_id) {
        context.addIssue({
          code: 'custom',
          path: ['assessments'],
          message: 'Assessment source identity does not match state.',
        });
      }
      const attempt = state.attempts.find((item) => item.id === assessment.attempt_id);
      if (
        !attempt ||
        attempt.status !== 'completed' ||
        attempt.assessment_id !== assessment.assessment_id ||
        attempt.finished_at !== assessment.finished_at ||
        attempt.map_revision !== assessment.map_revision ||
        attempt.section_id !== assessment.section_id ||
        attempt.provenance.cv_id !== assessment.cv_id ||
        attempt.provenance.cv_text_sha256 !== assessment.cv_text_sha256 ||
        attempt.provenance.source_sha256 !== assessment.source_sha256
      ) {
        context.addIssue({
          code: 'custom',
          path: ['assessments'],
          message: 'Assessment has no matching completed attempt.',
        });
      }
    }
    if (state.current_assessment) {
      const current = state.current_assessment;
      if (!state.assessments.some((item) => item.assessment_id === current.assessment_id)) {
        context.addIssue({
          code: 'custom',
          path: ['current_assessment'],
          message: 'Current assessment is absent from the saved assessment history.',
        });
      }
      if (
        current.topic_id !== state.topic_id ||
        current.file_id !== state.file_id ||
        current.map_revision !== state.map_revision ||
        current.cv_id !== state.selected_cv?.id ||
        current.cv_text_sha256 !== state.selected_cv?.extracted_sha256
      ) {
        context.addIssue({
          code: 'custom',
          path: ['current_assessment'],
          message: 'Current assessment does not match selected source metadata.',
        });
      }
    }
  });
export type PrerequisiteState = z.infer<typeof prerequisiteStateSchema>;

export const prerequisiteGenerationInputSchema = z
  .object({
    revision: sha256Schema,
    model: z.string().min(1).max(200),
    context_limit: z.number().int().min(1024).max(32768).optional(),
    think: z
      .union([z.boolean(), z.enum(['low', 'medium', 'high'])])
      .nullable()
      .optional(),
    goal: z.string().max(2000).nullable().optional(),
  })
  .strict();
export type PrerequisiteGenerationInput = z.infer<typeof prerequisiteGenerationInputSchema>;

export const prerequisiteStreamEventSchema = z.discriminatedUnion('type', [
  z
    .object({
      type: z.literal('started'),
      attempt_id: z.string().min(1),
      revision: sha256Schema,
      section_id: recordIdSchema,
      attempt: prerequisiteAttemptSchema,
    })
    .strict(),
  z.object({ type: z.literal('progress'), attempt_id: z.string().min(1), phase: z.literal('generating') }).strict(),
  z
    .object({
      type: z.literal('done'),
      attempt_id: z.string().min(1),
      assessment: prerequisiteAssessmentSchema,
      proficiency_revision: z.number().int().nonnegative(),
      attempt: prerequisiteAttemptSchema,
    })
    .strict(),
  z
    .object({
      type: z.literal('error'),
      attempt_id: z.string().min(1),
      message: z.string().min(1).max(2000),
      attempt: prerequisiteAttemptSchema,
    })
    .strict(),
]);
export type PrerequisiteStreamEvent = z.infer<typeof prerequisiteStreamEventSchema>;

export const prerequisiteImportInputSchema = z
  .object({
    file_id: recordIdSchema,
    assessment_id: z.string().min(1).max(100),
    revision: sha256Schema,
    section_id: recordIdSchema,
    expected_revision: z.number().int().nonnegative(),
  })
  .strict();
export type PrerequisiteImportInput = z.infer<typeof prerequisiteImportInputSchema>;

export const prerequisiteImportMessageSchema = messageSchema.extend({
  role: z.literal('user'),
  prerequisite_import: prerequisiteImportMetadataSchema,
});

export const prerequisiteImportResponseSchema = z
  .object({
    conversation_id: recordIdSchema,
    imported: z.boolean(),
    message: prerequisiteImportMessageSchema,
    messages: z.array(messageSchema),
    learner_context: learnerContextSchema,
    context: contextSchema.nullish(),
  })
  .strict();
export type PrerequisiteImportResponse = z.infer<typeof prerequisiteImportResponseSchema>;

export async function readPrerequisites(
  topicId: string,
  fileId: string,
  sectionId?: string,
  signal?: AbortSignal,
): Promise<PrerequisiteState> {
  const base = filePrerequisitesPath(topicId, fileId);
  const path = sectionId === undefined ? base : `${base}?section_id=${encodeURIComponent(sectionId)}`;
  return api(path, prerequisiteStateSchema, signal ? { signal } : {});
}

export async function streamPrerequisites(
  topicId: string,
  fileId: string,
  sectionId: string,
  input: PrerequisiteGenerationInput,
  signal: AbortSignal,
  onEvent: (event: PrerequisiteStreamEvent) => void,
  onAccepted: () => void = () => {},
): Promise<void> {
  const body = prerequisiteGenerationInputSchema.parse(input);
  const path = sectionPrerequisitesPath(topicId, fileId, sectionId);
  const response = await fetch(`/api${path}`, { ...json(body), signal });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, `Prerequisite request failed (${response.status})`));
  }
  onAccepted();
  if (!response.body) throw new Error('The server returned no prerequisite event stream.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let terminal = false;
  let attemptId: string | null = null;
  let startedAttempt: PrerequisiteAttempt | null = null;

  const consume = (line: string) => {
    if (!line.trim()) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch (error) {
      throw new Error('Invalid prerequisite event: line is not JSON.', { cause: error });
    }
    const result = prerequisiteStreamEventSchema.safeParse(parsed);
    if (!result.success) throw new Error(formatParseError('prerequisite event', result.error));
    const event = result.data;
    if (attemptId === null) {
      if (event.type !== 'started') throw new Error('Prerequisite stream did not start with an attempt.');
      attemptId = event.attempt_id;
      startedAttempt = event.attempt;
      if (
        event.attempt.id !== event.attempt_id ||
        event.attempt.status !== 'generating' ||
        event.attempt.map_revision !== event.revision ||
        event.attempt.section_id !== event.section_id ||
        event.revision !== body.revision ||
        event.section_id !== sectionId ||
        event.attempt.topic_id !== topicId ||
        event.attempt.file_id !== fileId
      ) {
        throw new Error('Prerequisite stream start does not match its attempt identity.');
      }
    } else if (event.attempt_id !== attemptId) {
      throw new Error('Prerequisite stream changed attempt identity.');
    }
    if (event.type === 'done') {
      if (
        !startedAttempt ||
        event.attempt.id !== attemptId ||
        !sameAttemptSource(startedAttempt, event.attempt) ||
        event.attempt.status !== 'completed' ||
        event.attempt.assessment_id !== event.assessment.assessment_id ||
        event.attempt_id !== event.assessment.attempt_id ||
        event.attempt.topic_id !== event.assessment.topic_id ||
        event.attempt.file_id !== event.assessment.file_id ||
        event.attempt.map_revision !== event.assessment.map_revision ||
        event.attempt.section_id !== event.assessment.section_id ||
        event.attempt.finished_at !== event.assessment.finished_at ||
        event.attempt.provenance.cv_id !== event.assessment.cv_id ||
        event.attempt.provenance.cv_text_sha256 !== event.assessment.cv_text_sha256 ||
        event.attempt.provenance.source_sha256 !== event.assessment.source_sha256
      ) {
        throw new Error('Completed prerequisite event does not match its assessment attempt.');
      }
      terminal = true;
    } else if (event.type === 'error') {
      if (
        !startedAttempt ||
        event.attempt.id !== attemptId ||
        !sameAttemptSource(startedAttempt, event.attempt) ||
        event.attempt.status !== 'error'
      ) {
        throw new Error('Failed prerequisite event does not match its attempt.');
      }
      terminal = true;
    }
    onEvent(event);
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
    if (!terminal) throw new Error('Connection ended before prerequisite generation completed.');
  } finally {
    await reader.cancel().catch(() => {
      /* the reader may already be closed after a terminal event */
    });
    reader.releaseLock();
  }
}

function sameAttemptSource(left: PrerequisiteAttempt, right: PrerequisiteAttempt): boolean {
  return (
    left.id === right.id &&
    left.assessment_id === right.assessment_id &&
    left.topic_id === right.topic_id &&
    left.file_id === right.file_id &&
    left.map_revision === right.map_revision &&
    left.section_id === right.section_id &&
    left.started_at === right.started_at &&
    left.provenance.prompt_version === right.provenance.prompt_version &&
    left.provenance.source_sha256 === right.provenance.source_sha256 &&
    left.provenance.runtime_policy_sha256 === right.provenance.runtime_policy_sha256 &&
    left.provenance.cv_id === right.provenance.cv_id &&
    left.provenance.cv_text_sha256 === right.provenance.cv_text_sha256 &&
    left.provenance.goal === right.provenance.goal &&
    left.provenance.model === right.provenance.model
  );
}

export function importPrerequisites(
  topicId: string,
  conversationId: string,
  input: PrerequisiteImportInput,
  signal?: AbortSignal,
): Promise<PrerequisiteImportResponse> {
  const checked = prerequisiteImportInputSchema.parse(input);
  const path = conversationPrerequisiteImportsPath(topicId, conversationId);
  return api(path, prerequisiteImportResponseSchema, {
    ...json(checked),
    ...(signal ? { signal } : {}),
  });
}
