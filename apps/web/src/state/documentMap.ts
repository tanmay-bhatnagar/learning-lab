import type { LabFile } from '../api/types';
import type { MapSection, SavedSummary, SummaryAttempt, SummaryStreamEvent } from '../api/documentMap';

export function mapUnavailableReason(file: LabFile): string | null {
  if (file.status !== 'ready') return 'not ready';
  if (file.parser !== 'docling' || !file.docling_name) return 'requires a Docling parse';
  return null;
}

export function findMapSection(sections: MapSection[], id: string): MapSection | null {
  for (const section of sections) {
    if (section.id === id) return section;
    const nested = findMapSection(section.children, id);
    if (nested) return nested;
  }
  return null;
}

export function mapSectionUnits(section: MapSection, units: DocumentMapUnit[]): DocumentMapUnit[] {
  const byId = new Map(units.map((unit) => [unit.id, unit]));
  return section.source_unit_ids.flatMap((id) => {
    const unit = byId.get(id);
    return unit ? [unit] : [];
  });
}

type DocumentMapUnit = { id: string; pages: number[]; included: boolean; warnings: string[] };

export type SummaryIdentity = { topic: string; fileId: string; revision: string; sectionId: string };

export type SectionSummaryState = SummaryIdentity & {
  attempt: SummaryAttempt | null;
  summary: SavedSummary | null;
  content: string;
  thinking: string;
  error: string;
};

export function sectionSummaryState(
  identity: SummaryIdentity,
  section: MapSection | null,
): SectionSummaryState {
  const attempt = section?.latest_attempt ?? null;
  const summary = section?.last_summary ?? null;
  return {
    ...identity,
    attempt,
    summary,
    content: attempt?.status === 'generating' ? attempt.content : summary?.content ?? '',
    thinking: '',
    error: attempt?.status === 'error' || attempt?.status === 'cancelled' ? (attempt.error ?? '') : '',
  };
}

export function foldSummaryEvent(
  previous: SectionSummaryState,
  event: SummaryStreamEvent,
  current: SummaryIdentity,
): SectionSummaryState {
  if (
    previous.topic !== current.topic ||
    previous.fileId !== current.fileId ||
    previous.revision !== current.revision ||
    previous.sectionId !== current.sectionId
  ) {
    return previous;
  }
  if (event.type === 'started') {
    if (
      event.revision !== current.revision ||
      event.section_id !== current.sectionId ||
      event.attempt_id !== event.attempt.id ||
      event.attempt.revision !== current.revision ||
      event.attempt.section_id !== current.sectionId
    ) {
      return previous;
    }
    return { ...previous, attempt: event.attempt, content: '', thinking: '', error: '' };
  }
  if (previous.attempt?.id !== event.attempt_id) return previous;
  if (event.type === 'token') return { ...previous, content: previous.content + event.text };
  if (event.type === 'thinking') return { ...previous, thinking: previous.thinking + event.text };
  if (event.type === 'done') {
    if (
      event.summary.id !== event.attempt_id ||
      event.summary.revision !== current.revision ||
      event.summary.section_id !== current.sectionId ||
      event.attempt.id !== event.attempt_id ||
      event.attempt.status !== 'completed'
    ) {
      return previous;
    }
    return { ...previous, summary: event.summary, attempt: event.attempt, content: event.summary.content, error: '' };
  }
  return {
    ...previous,
    ...(event.attempt?.id === event.attempt_id ? { attempt: event.attempt } : {}),
    error: event.message,
  };
}
