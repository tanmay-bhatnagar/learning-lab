import type { MessageRetrieval, RetrievalTraceMode } from './api';
import { retrievalModeLabel } from './domain/retrievalMode';

export function sourcesCount(retrieval: MessageRetrieval | undefined): number {
  return retrieval?.citations?.length ?? 0;
}

export function hasSources(retrieval: MessageRetrieval | undefined): boolean {
  return sourcesCount(retrieval) > 0 || Boolean(retrieval?.warning);
}

export function sourcesButtonLabel(count: number): string {
  return `Sources (${count})`;
}

export function modeBadgeLabel(mode: RetrievalTraceMode | undefined): string {
  return retrievalModeLabel(mode, 'No retrieval');
}

export function citationChunkLabel(chunkIndex: number | undefined): string | null {
  return chunkIndex == null ? null : `Chunk ${chunkIndex + 1}`;
}
