import type { EvidenceSearchMetadata, StreamEvent } from '../api/types';

export type EvidenceSearchStage = 'deciding' | 'searching' | 'answering';

export type EvidenceSearchProgress = {
  stage: EvidenceSearchStage;
  warning?: string;
};

export type EvidenceSearchFollowUp = 'none' | 'no_results' | 'duplicates' | 'trimmed' | 'retained';

export type EvidenceSearchSummary = {
  outcome: EvidenceSearchMetadata['outcome'];
  generationCount: number;
  lookupCount: number;
  followUp: EvidenceSearchFollowUp;
  initialAvailableCount: number;
  initialRetainedCount: number;
  returnedCount: number;
  novelReturnedCount: number;
  retainedNewCount: number;
  finalRetainedCount: number;
  declaredSourceLabels: string[];
  warning?: string;
};

export function foldEvidenceSearchProgress(
  current: EvidenceSearchProgress | null,
  event: StreamEvent,
): EvidenceSearchProgress | null {
  if (event.type === 'done' || event.type === 'error') return null;
  if (event.type !== 'evidence_status') return current;
  return event.warning ? { stage: event.stage, warning: event.warning } : { stage: event.stage };
}

export function summarizeEvidenceSearch(
  metadata: EvidenceSearchMetadata | null | undefined,
): EvidenceSearchSummary | null {
  if (!metadata) return null;

  const followUp: EvidenceSearchFollowUp =
    metadata.outcome !== 'searched'
      ? 'none'
      : metadata.returned_chunk_ids.length === 0
        ? 'no_results'
        : metadata.new_chunk_ids.length === 0
          ? 'duplicates'
          : metadata.retained_new_chunk_ids.length === 0
            ? 'trimmed'
            : 'retained';
  const warning = metadata.warning || metadata.search_warning || undefined;

  return {
    outcome: metadata.outcome,
    generationCount: metadata.generation_count,
    lookupCount: metadata.lookup_count,
    followUp,
    initialAvailableCount: metadata.initial_available_chunk_ids.length,
    initialRetainedCount: metadata.initial_chunk_ids.length,
    returnedCount: metadata.returned_chunk_ids.length,
    novelReturnedCount: metadata.new_chunk_ids.length,
    retainedNewCount: metadata.retained_new_chunk_ids.length,
    finalRetainedCount: metadata.final_chunk_ids.length,
    declaredSourceLabels: [...metadata.declared_source_labels],
    ...(warning ? { warning } : {}),
  };
}
