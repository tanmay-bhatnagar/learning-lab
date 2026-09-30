import type { MessageRetrieval, RetrievalTraceMode } from './api/types';
import { retrievalModeLabel } from './domain/retrievalMode';

export function sourcesCount(retrieval: MessageRetrieval | null | undefined): number {
  return retrieval?.citations?.length ?? 0;
}

export function hasSources(retrieval: MessageRetrieval | null | undefined): boolean {
  return sourcesCount(retrieval) > 0 || Boolean(retrieval?.warning);
}

export function sourcesButtonLabel(count: number): string {
  return `Sources (${count})`;
}

export function modeBadgeLabel(mode: RetrievalTraceMode | undefined): string {
  return retrievalModeLabel(mode, 'No retrieval');
}

export function citationChunkLabel(chunkIndex: number | null | undefined): string | null {
  return chunkIndex == null ? null : `Chunk ${chunkIndex + 1}`;
}
