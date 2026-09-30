import React, { useId, useState } from 'react';
import { BookOpen, ChevronDown } from 'lucide-react';
import type { Citation, LabFile, MessageRetrieval } from './api/types';
import { originalPdfUrl } from './api/urls';
import { headingsLabel, pagesLabel } from './retrievalTraceHelpers';
import { citationChunkLabel, hasSources, modeBadgeLabel, sourcesButtonLabel } from './citationsHelpers';
import { VisualAssets } from './components/VisualAssets';

function CitationCard({
  citation,
  file,
  topic,
  index,
}: {
  citation: Citation;
  file: LabFile | undefined;
  topic: string;
  index: number;
}) {
  const chunkLabel = citationChunkLabel(citation.chunk_index);
  const pages = [...new Set(citation.pages)].filter((page) => Number.isInteger(page) && page > 0).sort((a, b) => a - b);
  const unavailablePages = pages.filter((page) => file?.page_count != null && page > file.page_count);
  const readyFile = file?.status === 'ready' ? file : undefined;
  return (
    <article className="citation-card" aria-labelledby={`citation-${citation.chunk_id}-${index}`}>
      <header className="citation-card-header">
        <h4 id={`citation-${citation.chunk_id}-${index}`}>{citation.file_name}</h4>
        <p className="citation-card-meta">
          {headingsLabel(citation.headings)} ·{' '}
          {pages.length
            ? pages.map((page) =>
                readyFile && !unavailablePages.includes(page) ? (
                  <React.Fragment key={page}>
                    <a href={originalPdfUrl(topic, readyFile.id, page)} target="_blank" rel="noopener noreferrer">
                      Page {page}
                    </a>
                    {page !== pages[pages.length - 1] ? ', ' : ''}
                  </React.Fragment>
                ) : (
                  <React.Fragment key={page}>
                    Page {page} unavailable{page !== pages[pages.length - 1] ? ', ' : ''}
                  </React.Fragment>
                ),
              )
            : citation.pages.length
              ? 'Page target unavailable'
              : pagesLabel(citation.pages)}
          {chunkLabel ? ` · ${chunkLabel}` : ''}
        </p>
      </header>
      {citation.text && <pre className="citation-excerpt">{citation.text}</pre>}
      <VisualAssets topic={topic} file={file} assetRefs={citation.assets || []} classNamePrefix="citation" />
    </article>
  );
}

export function MessageSources({
  topic,
  files,
  retrieval,
}: {
  topic: string;
  files: LabFile[];
  retrieval?: MessageRetrieval;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  if (!hasSources(retrieval)) return null;
  const sources = retrieval!;
  const count = sources.citations.length;
  const fileById = new Map(files.map((file) => [file.id, file]));
  return (
    <div className="message-sources">
      <button
        type="button"
        className="sources-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <BookOpen size={13} aria-hidden="true" />
        <span>{sourcesButtonLabel(count)}</span>
        <span className="sources-mode-badge">{modeBadgeLabel(sources.mode)}</span>
        <ChevronDown size={14} className={`sources-chevron ${open ? 'open' : ''}`} aria-hidden="true" />
      </button>
      {sources.warning && (
        <p className="sources-warning" role="status">
          {sources.warning}
        </p>
      )}
      {open && (
        <div className="sources-panel" id={panelId}>
          {sources.citations.map((citation, index) => (
            <CitationCard
              key={`${citation.chunk_id}-${index}`}
              citation={citation}
              file={fileById.get(citation.file_id)}
              topic={topic}
              index={index}
            />
          ))}
        </div>
      )}
    </div>
  );
}
