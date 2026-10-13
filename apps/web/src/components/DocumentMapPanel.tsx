import { LoaderCircle, RefreshCw, Sparkles, Square } from 'lucide-react';
import type { LabFile } from '../api/types';
import type { DocumentMap, MapSection, SavedSummary } from '../api/documentMap';
import { originalPdfUrl } from '../api/urls';
import type { SectionSummaryState } from '../state/documentMap';
import { mapUnavailableReason } from '../state/documentMap';
import { RichText } from './RichText';

type Props = {
  topic: string;
  files: LabFile[];
  fileId: string;
  onFileChange: (id: string) => void;
  map: DocumentMap | null;
  status: 'not_built' | 'ready' | 'stale' | null;
  loading: boolean;
  busy: boolean;
  error: string;
  conversationTitle: string;
  selectedSectionId: string;
  summaryView: SectionSummaryState | null;
  summaryRunning: boolean;
  summaryImporting: boolean;
  summaryNotice: string;
  onSelectSection: (id: string) => void;
  onGenerateSummary: () => void;
  onStopSummary: () => void;
  onAddSummary: () => void;
  onBuild: () => void;
  onRetry: () => void;
};

function SectionTree({
  sections,
  topic,
  fileId,
  selectedSectionId,
  selectionDisabled,
  onSelectSection,
}: {
  sections: MapSection[];
  topic: string;
  fileId: string;
  selectedSectionId: string;
  selectionDisabled: boolean;
  onSelectSection: (id: string) => void;
}) {
  return (
    <ul className="document-map-tree">
      {sections.map((section) => (
        <li key={section.id}>
          <details open>
            <summary>
              <span>{section.title || 'Untitled section'}</span>
              <span className="muted">
                {section.pages.length ? ` · pp. ${section.pages.join(', ')}` : ' · page unknown'}
              </span>
            </summary>
            <div className="map-section-preview">
              <p>{section.text || 'No direct preview text was extracted.'}</p>
              <small>Direct extracted text. A generated summary covers this section and its nested sections.</small>
              <button className="text-button" disabled={selectionDisabled} onClick={() => onSelectSection(section.id)}>
                {selectedSectionId === section.id ? 'Selected section' : 'Select section'}
              </button>
              {section.pages.length > 0 && (
                <div className="map-pages">
                  {section.pages.map((page) => (
                    <a key={page} href={originalPdfUrl(topic, fileId, page)} target="_blank" rel="noreferrer">
                      Page {page}
                    </a>
                  ))}
                </div>
              )}
            </div>
            {section.children.length > 0 && (
              <SectionTree
                sections={section.children}
                topic={topic}
                fileId={fileId}
                selectedSectionId={selectedSectionId}
                selectionDisabled={selectionDisabled}
                onSelectSection={onSelectSection}
              />
            )}
          </details>
        </li>
      ))}
    </ul>
  );
}

export function DocumentMapPanel({
  topic,
  files,
  fileId,
  onFileChange,
  map,
  status,
  loading,
  busy,
  error,
  conversationTitle,
  selectedSectionId,
  summaryView,
  summaryRunning,
  summaryImporting,
  summaryNotice,
  onSelectSection,
  onGenerateSummary,
  onStopSummary,
  onAddSummary,
  onBuild,
  onRetry,
}: Props) {
  const selected = files.find((file) => file.id === fileId);
  const readyMap = map && selected ? map : null;
  const buildLabel = status === 'stale' ? 'Rebuild outline' : 'Build outline';
  const included = readyMap?.coverage.included_units ?? 0;
  const excluded = readyMap?.coverage.excluded_units ?? 0;

  return (
    <section className="document-map-panel" aria-labelledby="document-map-title">
      <header className="document-map-header">
        <div>
          <h2 id="document-map-title">Document map</h2>
          <p className="muted">Build an outline for one PDF when you need it. This does not change chat attachments.</p>
        </div>
        <label>
          PDF for map
          <select aria-label="PDF for map" value={fileId} onChange={(event) => onFileChange(event.target.value)}>
            <option value="">Choose a PDF…</option>
            {files.map((file) => {
              const reason = mapUnavailableReason(file);
              return (
                <option key={file.id} value={file.id} disabled={!!reason}>
                  {file.name}
                  {reason ? ` — not supported: ${reason}` : ''}
                </option>
              );
            })}
          </select>
        </label>
      </header>

      {!fileId && <p className="map-empty">Choose a ready PDF processed with Docling to view or build its outline.</p>}
      {!fileId && (
        <div className="map-actions">
          <button className="primary" disabled>
            <RefreshCw size={16} />
            Build outline
          </button>
        </div>
      )}
      {fileId && selected && mapUnavailableReason(selected) && (
        <p className="map-empty">This file cannot be mapped: {mapUnavailableReason(selected)}.</p>
      )}
      {fileId && selected && !mapUnavailableReason(selected) && (
        <>
          <div className="map-actions">
            <button className="primary" disabled={busy || loading} onClick={onBuild}>
              {loading ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />}
              {loading ? 'Working…' : buildLabel}
            </button>
            {status === 'not_built' && <span className="muted">No outline saved yet.</span>}
            {summaryRunning && (
              <button className="text-button" onClick={onStopSummary}>
                <Square size={14} /> Stop summary
              </button>
            )}
          </div>
          {error && (
            <div className="map-error" role="alert">
              <span>{error}</span>
              <button className="text-button" onClick={onRetry}>
                Retry
              </button>
            </div>
          )}
          {status === 'stale' && (
            <p className="map-warning">This outline is out of date. Rebuild it to match the current source file.</p>
          )}
          {readyMap && (
            <>
              <div className="map-coverage" aria-label="Source coverage">
                <strong>Extracted source accounting</strong>
                <span>{included} included extracted units</span>
                <span>{excluded} excluded extracted units</span>
                <span>
                  {readyMap.coverage.accounted_source_items} of {readyMap.coverage.total_source_items} source items
                  accounted
                </span>
                <span>Accounting describes parser output; it does not measure document completeness.</span>
              </div>
              <p className="map-outline-mode">
                {readyMap.outline_mode === 'pages'
                  ? 'Outline method: page groups from extracted items.'
                  : 'Outline method: detected headings; hierarchy reflects the stored document structure.'}
              </p>
              {readyMap.warnings.length > 0 && (
                <ul className="map-warning-list">
                  {readyMap.warnings.map((warning, index) => (
                    <li key={`${index}:${warning}`}>{warning}</li>
                  ))}
                </ul>
              )}
              {readyMap.sections.length ? (
                <SectionTree
                  sections={readyMap.sections}
                  topic={topic}
                  fileId={fileId}
                  selectedSectionId={selectedSectionId}
                  selectionDisabled={summaryRunning}
                  onSelectSection={onSelectSection}
                />
              ) : (
                <p className="map-empty">No outline sections were found in this document.</p>
              )}
              <SectionSummaryCard
                sectionTitle={selectedSectionId ? findSectionTitle(readyMap.sections, selectedSectionId) : ''}
                summary={summaryView?.sectionId === selectedSectionId ? summaryView.summary : null}
                attempt={summaryView?.sectionId === selectedSectionId ? summaryView.attempt : null}
                draft={summaryView?.sectionId === selectedSectionId ? summaryView.content : ''}
                error={summaryView?.sectionId === selectedSectionId ? summaryView.error : ''}
                running={summaryRunning}
                importing={summaryImporting}
                notice={summaryNotice}
                busy={busy || status !== 'ready'}
                conversationTitle={conversationTitle}
                topic={topic}
                fileId={fileId}
                units={readyMap.units}
                pageCount={selected.page_count}
                onGenerate={onGenerateSummary}
                onStop={onStopSummary}
                onAdd={onAddSummary}
              />
              {readyMap.units.some((unit) => unit.pages.length > 0) && (
                <div className="map-pages">
                  <strong>Original PDF pages</strong>
                  {[...new Set(readyMap.units.flatMap((unit) => unit.pages))]
                    .sort((a, b) => a - b)
                    .map((page) => (
                      <a key={page} href={originalPdfUrl(topic, fileId, page)} target="_blank" rel="noreferrer">
                        Page {page}
                      </a>
                    ))}
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}

function findSectionTitle(sections: MapSection[], id: string): string {
  for (const section of sections) {
    if (section.id === id) return section.title;
    const child = findSectionTitle(section.children, id);
    if (child) return child;
  }
  return '';
}

function SectionSummaryCard({
  sectionTitle,
  summary,
  attempt,
  draft,
  error,
  running,
  importing,
  notice,
  busy,
  conversationTitle,
  topic,
  fileId,
  units,
  pageCount,
  onGenerate,
  onStop,
  onAdd,
}: {
  sectionTitle: string;
  summary: SavedSummary | null;
  attempt: SectionSummaryState['attempt'];
  draft: string;
  error: string;
  running: boolean;
  importing: boolean;
  notice: string;
  busy: boolean;
  conversationTitle: string;
  topic: string;
  fileId: string;
  units: DocumentMap['units'];
  pageCount?: number | null;
  onGenerate: () => void;
  onStop: () => void;
  onAdd: () => void;
}) {
  if (!sectionTitle) return null;
  const unitById = new Map(units.map((unit) => [unit.id, unit]));
  return (
    <section
      id="selected-section-summary"
      className="section-summary-card"
      aria-labelledby="section-summary-title"
      tabIndex={-1}
    >
      <div className="section-summary-header">
        <div>
          <span className="eyebrow">ON-DEMAND SUMMARY</span>
          <h3 id="section-summary-title">{sectionTitle}</h3>
          <p className="muted">
            The selected section and all nested sections are sent in full to the current local model.
          </p>
        </div>
        {running ? (
          <button className="text-button" onClick={onStop}>
            <Square size={14} /> Stop
          </button>
        ) : (
          <button className="primary" disabled={busy} onClick={onGenerate}>
            <Sparkles size={15} />{' '}
            {summary ? 'Regenerate summary' : attempt?.status === 'error' ? 'Retry summary' : 'Generate summary'}
          </button>
        )}
      </div>
      {running && (
        <p className="map-summary-progress" role="status">
          Generating. Any partial text below is not saved as a completed summary.
        </p>
      )}
      {summary && (
        <article className="map-summary-result">
          <div className="map-summary-meta">
            <strong>Saved summary</strong>
            <span>{summary.model}</span>
            <time dateTime={summary.created_at}>{new Date(summary.created_at).toLocaleString()}</time>
          </div>
          <p className="muted">
            Generated summary, not verbatim PDF text. Source labels show where it came from; they do not verify each
            claim.
          </p>
          <RichText text={summary.content} />
          <div className="summary-source-list" aria-label="Summary source units">
            <strong>Source units</strong>
            {summary.sources.map((source) => {
              const unit = unitById.get(source.unit_id);
              const pages = [...new Set(source.pages)].sort((a, b) => a - b);
              const validPages = pages.filter((page) => page > 0 && (pageCount == null || page <= pageCount));
              return (
                <div className="summary-source-item" key={source.label}>
                  <strong>[{source.label}]</strong>
                  <span>{unit?.text || 'Source text preview unavailable.'}</span>
                  <div className="map-pages">
                    {validPages.map((page) => (
                      <a key={page} href={originalPdfUrl(topic, fileId, page)} target="_blank" rel="noreferrer">
                        Page {page}
                      </a>
                    ))}
                    {pages.length === 0 && <span>Page unknown</span>}
                    {pages.length > validPages.length && pages.length > 0 && <span>Some page targets unavailable</span>}
                  </div>
                </div>
              );
            })}
          </div>
          <button className="secondary" disabled={busy || importing || !conversationTitle} onClick={onAdd}>
            {importing ? 'Adding…' : `Add to “${conversationTitle}”`}
          </button>
        </article>
      )}
      {!summary && !running && attempt?.status === 'generating' && (
        <p className="map-summary-progress" role="status">
          A previous generation stopped before it could be verified. Retry to continue.
        </p>
      )}
      {!summary && !running && attempt && ['error', 'cancelled', 'interrupted'].includes(attempt.status) && (
        <p className="map-warning">Previous attempt: {attempt.status}. Its text is not a saved summary.</p>
      )}
      {(running || (attempt && attempt.status !== 'completed' && draft)) && (
        <div className="map-summary-draft">
          <strong>Incomplete attempt</strong>
          <p>{draft || 'Waiting for text…'}</p>
        </div>
      )}
      {error && (
        <p className="map-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="map-summary-notice" role="status">
          {notice}
        </p>
      )}
    </section>
  );
}
