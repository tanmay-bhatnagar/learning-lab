export type ComfortLevel = 'comfortable' | 'refresher' | 'new' | 'unsure';
export type ComfortAnswer = ComfortLevel | '';

export type ProficiencyDraft = {
  id: string;
  concept: string;
  comfort: ComfortAnswer;
  note: string;
  kind: 'requirement' | 'manual';
  requirementId?: string;
};

export type RequirementView = {
  id: string;
  concept: string;
  rationale: string;
  sourceLabel: string;
};

export type ProficiencyEntryView = ProficiencyDraft & {
  kind: 'manual';
};

export type CvView = {
  id: string;
  originalName: string;
  status: 'ready' | 'processing' | 'error' | 'revoked';
  extractedText: string;
  extractionDiagnostics: string[];
};

export function createRequirementDraft(
  requirement: RequirementView,
  entries: ProficiencyEntryView[],
): ProficiencyDraft {
  const saved = entries.find((entry) => entry.requirementId === requirement.id);
  return {
    id: saved?.id ?? `requirement:${requirement.id}`,
    concept: requirement.concept,
    comfort: saved?.comfort ?? '',
    note: saved?.note ?? '',
    kind: 'requirement',
    requirementId: requirement.id,
  };
}

export function hasDuplicateConcept(concept: string, drafts: ProficiencyDraft[]): boolean {
  const normalized = concept.trim().normalize('NFKC').toLocaleLowerCase();
  return (
    !!normalized && drafts.some((draft) => draft.concept.trim().normalize('NFKC').toLocaleLowerCase() === normalized)
  );
}

export function mergeRefreshedDrafts(
  current: ProficiencyDraft[],
  incoming: ProficiencyDraft[],
  requirementIds: string[],
): ProficiencyDraft[] {
  const visibleRequirements = new Set(requirementIds);
  const retained = current.filter(
    (draft) => draft.kind === 'manual' || (!!draft.requirementId && visibleRequirements.has(draft.requirementId)),
  );
  const existingIds = new Set(retained.map((draft) => draft.id));
  return [...retained, ...incoming.filter((draft) => !existingIds.has(draft.id))];
}
