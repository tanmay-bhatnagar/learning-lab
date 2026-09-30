import React, { useId, useState } from 'react';
import { BookOpen, ChevronDown } from 'lucide-react';
import type { Citation, LabFile, MessageRetrieval } from './api';
import { assetApiUrl, headingsLabel, pagesLabel, resolveAssetId } from './retrievalTraceHelpers';
import { citationChunkLabel, hasSources, modeBadgeLabel, sourcesButtonLabel } from './citationsHelpers';

function CitationAssets({ topic, file, assets }: { topic: string; file: LabFile | undefined; assets: string[] }) {
  if (!assets.length) return null;
  return (
    <div className="citation-assets" aria-label="Linked visuals">
      {assets.map(ref => {
        const assetId = resolveAssetId(file, ref);
        const asset = file?.assets?.find(item => item.id === assetId || item.name === ref);
        if (!assetId) {
          return (
            <figure className="citation-asset citation-asset-missing" key={ref}>
              <span className="citation-asset-placeholder">Visual unavailable</span>
              <figcaption>{asset?.caption || ref}</figcaption>
            </figure>
          );
        }
        return (
          <figure className="citation-asset" key={assetId}>
            <a href={assetApiUrl(topic, file!.id, assetId)} target="_blank" rel="noopener noreferrer">
              <img src={assetApiUrl(topic, file!.id, assetId)} alt={asset?.caption || asset?.kind || 'Document visual'} loading="lazy" />
            </a>
            <figcaption>{asset?.caption || `${asset?.kind || 'visual'}${asset?.page != null ? ` · p.${asset.page}` : ''}`}</figcaption>
          </figure>
        );
      })}
    </div>
  );
}

function CitationCard({ citation, file, topic, index }: { citation: Citation; file: LabFile | undefined; topic: string; index: number }) {
  const chunkLabel = citationChunkLabel(citation.chunk_index);
  return (
    <article className="citation-card" aria-labelledby={`citation-${citation.chunk_id}-${index}`}>
      <header className="citation-card-header">
        <h4 id={`citation-${citation.chunk_id}-${index}`}>{citation.file_name}</h4>
        <p className="citation-card-meta">{headingsLabel(citation.headings)} · {pagesLabel(citation.pages)}{chunkLabel ? ` · ${chunkLabel}` : ''}</p>
      </header>
      {citation.text && <pre className="citation-excerpt">{citation.text}</pre>}
      <CitationAssets topic={topic} file={file} assets={citation.assets || []} />
    </article>
  );
}

export function MessageSources({ topic, files, retrieval }: { topic: string; files: LabFile[]; retrieval?: MessageRetrieval }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  if (!hasSources(retrieval)) return null;
  const count = retrieval!.citations.length;
  const fileById = new Map(files.map(file => [file.id, file]));
  return (
    <div className="message-sources">
      <button type="button" className="sources-toggle" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(value => !value)}>
        <BookOpen size={13} aria-hidden="true" />
        <span>{sourcesButtonLabel(count)}</span>
        <span className="sources-mode-badge">{modeBadgeLabel(retrieval!.mode)}</span>
        <ChevronDown size={14} className={`sources-chevron ${open ? 'open' : ''}`} aria-hidden="true" />
      </button>
      {retrieval!.warning && <p className="sources-warning" role="status">{retrieval!.warning}</p>}
      {open && (
        <div className="sources-panel" id={panelId}>
          {retrieval!.citations.map((citation, index) => (
            <CitationCard key={`${citation.chunk_id}-${index}`} citation={citation} file={fileById.get(citation.file_id)} topic={topic} index={index} />
          ))}
        </div>
      )}
    </div>
  );
}
