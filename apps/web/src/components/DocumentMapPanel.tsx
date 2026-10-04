import { LoaderCircle, RefreshCw } from 'lucide-react';
import type { LabFile } from '../api/types';
import type { DocumentMap, MapSection } from '../api/documentMap';
import { originalPdfUrl } from '../api/urls';
import { mapUnavailableReason } from '../state/documentMap';

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
  onBuild: () => void;
  onRetry: () => void;
};

function SectionTree({ sections, topic, fileId }: { sections: MapSection[]; topic: string; fileId: string }) {
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
              <small>Direct extracted text. Future summaries will include this section and its nested sections.</small>
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
            {section.children.length > 0 && <SectionTree sections={section.children} topic={topic} fileId={fileId} />}
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
                <SectionTree sections={readyMap.sections} topic={topic} fileId={fileId} />
              ) : (
                <p className="map-empty">No outline sections were found in this document.</p>
              )}
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
