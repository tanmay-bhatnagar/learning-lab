import type { RetrievalTraceMode } from '../api/types';

export function retrievalModeLabel(mode: RetrievalTraceMode | undefined, emptyLabel: string): string {
  switch (mode) {
    case 'hybrid':
      return 'Hybrid (keyword + embeddings + RRF)';
    case 'keyword':
      return 'Keyword only';
    case 'fallback':
      return 'Fallback opening chunks';
    default:
      return emptyLabel;
  }
}
