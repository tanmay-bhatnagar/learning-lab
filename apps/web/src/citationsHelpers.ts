import type { MessageRetrieval, RetrievalTraceMode } from './api';

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
  switch (mode) {
    case 'hybrid': return 'Hybrid (keyword + embeddings + RRF)';
    case 'keyword': return 'Keyword only';
    case 'fallback': return 'Fallback opening chunks';
    default: return 'No retrieval';
  }
}

export function citationLocation(fileName: string, headings: string[] | undefined, pages: number[] | undefined): string {
  const parts = [fileName];
  if (headings?.length) parts.push(headings.join(' › '));
  if (pages?.length) parts.push(pages.length === 1 ? `Page ${pages[0]}` : `Pages ${pages.join(', ')}`);
  return parts.join(' · ');
}

export function citationChunkLabel(chunkIndex: number | undefined): string | null {
  return chunkIndex == null ? null : `Chunk ${chunkIndex + 1}`;
}
