import type { FileChunk, LabFile, RetrievalTraceRequest, RetrievalTraceResponse, TraceComponent } from './api';

export function isIndexedFile(file: LabFile): boolean {
  return file.index_status === 'ready' && file.status === 'ready';
}

export function indexedSelectedIds(files: LabFile[], selected: string[]): string[] {
  const byId = new Map(files.map((file) => [file.id, file]));
  return [
    ...new Set(
      selected.filter((id) => {
        const file = byId.get(id);
        return file ? isIndexedFile(file) : false;
      }),
    ),
  ];
}

export function traceRequest(query: string, fileIds: string[], topK: number): RetrievalTraceRequest {
  return { query: query.trim(), file_ids: [...new Set(fileIds)], top_k: topK };
}

export function resolveAssetId(file: LabFile | undefined, assetRef: string): string | null {
  if (!file?.assets?.length || !assetRef) return null;
  const direct = file.assets.find((asset) => asset.id === assetRef);
  if (direct) return direct.id;
  const byName = file.assets.find((asset) => asset.name === assetRef);
  return byName?.id ?? null;
}

export function assetApiUrl(topic: string, fileId: string, assetId: string): string {
  return `/api/topics/${encodeURIComponent(topic)}/files/${encodeURIComponent(fileId)}/assets/${encodeURIComponent(assetId)}`;
}

export function formatRank(rank: number | null | undefined): string {
  return rank == null ? '—' : `#${rank}`;
}

export function formatTraceScore(component: TraceComponent, channel: 'keyword' | 'embedding' | 'fusion'): string {
  if (component.score == null) return '—';
  if (channel === 'embedding') {
    const value = component.cosine ?? component.score;
    return typeof value === 'number' ? value.toFixed(4) : '—';
  }
  if (channel === 'keyword') return component.score.toFixed(3);
  return component.score.toFixed(5);
}

export function chunkDisplayText(chunk: Pick<FileChunk, 'contextualized_text' | 'text'>): string {
  return (chunk.contextualized_text || chunk.text || '').trim();
}

export function modeLabel(mode: RetrievalTraceResponse['mode']): string {
  switch (mode) {
    case 'hybrid':
      return 'Hybrid (keyword + embeddings + RRF)';
    case 'keyword':
      return 'Keyword only';
    case 'fallback':
      return 'Fallback opening chunks';
    default:
      return 'No matches';
  }
}

export function pagesLabel(pages: number[] | undefined): string {
  if (!pages?.length) return 'No page';
  return pages.length === 1 ? `Page ${pages[0]}` : `Pages ${pages.join(', ')}`;
}

export function headingsLabel(headings: string[] | undefined): string {
  return headings?.length ? headings.join(' › ') : 'No heading';
}
