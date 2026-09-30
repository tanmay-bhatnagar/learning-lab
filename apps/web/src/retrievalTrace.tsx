import React, { useMemo, useState } from 'react';
import { ChevronRight, FileText, LoaderCircle, ScanSearch } from 'lucide-react';
import { api, assetApiUrl, fileChunksPath, json, retrievalTracePath } from './api';
import type { FileChunk, LabFile, RetrievalTraceHit, RetrievalTraceResponse } from './api';
import {
  chunkDisplayText,
  formatRank,
  formatTraceScore,
  headingsLabel,
  indexedSelectedIds,
  modeLabel,
  pagesLabel,
  resolveAssetId,
  traceRequest,
} from './retrievalTraceHelpers';

type LoadedChunks = { fileId: string; fileName: string; chunks: FileChunk[] };

type Props = {
  topic: string;
  files: LabFile[];
  selected: string[];
  topK: number;
  busy: boolean;
  topicReady: boolean;
  onOpenFiles: () => void;
};

function TraceMetric({ label, rank, score, hint }: { label: string; rank: string; score: string; hint?: string }) {
  return (
    <div className="trace-metric">
      <span className="trace-metric-label">{label}</span>
      <strong>{rank}</strong>
      <span className="trace-metric-score">
        {score}
        {hint ? <small>{hint}</small> : null}
      </span>
    </div>
  );
}

function AssetThumbnails({
  topic,
  file,
  assetRefs,
}: {
  topic: string;
  file: LabFile | undefined;
  assetRefs: string[];
}) {
  if (!assetRefs.length) return null;
  return (
    <div className="trace-assets" aria-label="Linked visuals">
      {assetRefs.map((ref) => {
        const assetId = resolveAssetId(file, ref);
        const asset = file?.assets?.find((item) => item.id === assetId || item.name === ref);
        if (!assetId) {
          return (
            <figure className="trace-asset trace-asset-missing" key={ref}>
              <span className="trace-asset-placeholder">Visual unavailable</span>
              <figcaption>{asset?.caption || ref}</figcaption>
            </figure>
          );
        }
        return (
          <figure className="trace-asset" key={assetId}>
            <a href={assetApiUrl(topic, file!.id, assetId)} target="_blank" rel="noopener noreferrer">
              <img
                src={assetApiUrl(topic, file!.id, assetId)}
                alt={asset?.caption || asset?.kind || 'Document visual'}
                loading="lazy"
              />
            </a>
            <figcaption>
              {asset?.caption || `${asset?.kind || 'visual'}${asset?.page != null ? ` · p.${asset.page}` : ''}`}
            </figcaption>
          </figure>
        );
      })}
    </div>
  );
}

function HitCard({
  hit,
  file,
  topic,
  evidenceRank,
}: {
  hit: RetrievalTraceHit;
  file: LabFile | undefined;
  topic: string;
  evidenceRank: number;
}) {
  const assetRefs = hit.asset_ids?.length ? hit.asset_ids : [];
  return (
    <article className="trace-hit" aria-labelledby={`hit-${hit.chunk_id}`}>
      <header className="trace-hit-header">
        <span className="trace-evidence-badge">Evidence #{evidenceRank}</span>
        <h3 id={`hit-${hit.chunk_id}`}>{hit.file_name}</h3>
        <p className="trace-hit-meta">
          {headingsLabel(hit.headings)} · {pagesLabel(hit.pages)} · chunk {hit.chunk_index + 1}
        </p>
      </header>
      <div className="trace-metrics" role="group" aria-label="Retrieval ranks and scores">
        <TraceMetric
          label="Keyword"
          rank={formatRank(hit.trace.keyword.rank)}
          score={formatTraceScore(hit.trace.keyword, 'keyword')}
          hint="BM25, lower is better"
        />
        <TraceMetric
          label="Embedding"
          rank={formatRank(hit.trace.embedding.rank)}
          score={formatTraceScore(hit.trace.embedding, 'embedding')}
          hint="cosine, higher is better"
        />
        <TraceMetric
          label="RRF fusion"
          rank={formatRank(hit.trace.fusion.rank)}
          score={formatTraceScore(hit.trace.fusion, 'fusion')}
          hint="higher is better"
        />
      </div>
      <pre className="trace-chunk-text">{hit.text}</pre>
      <AssetThumbnails topic={topic} file={file} assetRefs={assetRefs} />
    </article>
  );
}

function SourceChunkCard({
  chunk,
  file,
  topic,
  selected,
}: {
  chunk: FileChunk;
  file: LabFile;
  topic: string;
  selected: boolean;
}) {
  const text = chunkDisplayText(chunk);
  const assetRefs = chunk.asset_names?.length ? chunk.asset_names : [];
  return (
    <article className={`trace-source-chunk ${selected ? 'selected' : ''}`}>
      <header>
        <strong>{file.name}</strong>
        <span>
          {headingsLabel(chunk.headings)} · {pagesLabel(chunk.pages)}
          {chunk.chunk_id ? ` · ${chunk.chunk_id}` : ''}
        </span>
        {selected && <span className="trace-selected-chip">Selected evidence</span>}
      </header>
      <pre>{text || '(empty chunk)'}</pre>
      <AssetThumbnails topic={topic} file={file} assetRefs={assetRefs} />
    </article>
  );
}

export function RetrievalTracePanel({ topic, files, selected, topK, busy, topicReady, onOpenFiles }: Props) {
  const [query, setQuery] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<RetrievalTraceResponse | null>(null);
  const [loadedChunks, setLoadedChunks] = useState<LoadedChunks[]>([]);

  const indexedIds = useMemo(() => indexedSelectedIds(files, selected), [files, selected]);
  const filesById = useMemo(() => new Map(files.map((file) => [file.id, file])), [files]);
  const selectedNames = useMemo(() => indexedIds.map((id) => filesById.get(id)?.name || id), [indexedIds, filesById]);
  const evidenceIds = useMemo(() => new Set(result?.hits.map((hit) => hit.chunk_id) ?? []), [result]);

  async function runTrace(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim() || !indexedIds.length || running || busy || !topicReady) return;
    setRunning(true);
    setError('');
    setResult(null);
    setLoadedChunks([]);
    const body = traceRequest(query, indexedIds, topK);
    try {
      const [trace, ...chunkSets] = await Promise.all([
        api<RetrievalTraceResponse>(retrievalTracePath(topic), json(body)),
        ...indexedIds.map(async (fileId) => {
          const file = filesById.get(fileId);
          const payload = await api<{ chunks: FileChunk[] }>(fileChunksPath(topic, fileId));
          return { fileId, fileName: file?.name || fileId, chunks: payload.chunks };
        }),
      ]);
      setResult(trace);
      setLoadedChunks(chunkSets);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Retrieval trace failed.');
    } finally {
      setRunning(false);
    }
  }

  const canRun = !!query.trim() && indexedIds.length > 0 && !running && !busy && topicReady;

  return (
    <div className="trace-page">
      <div className="trace-toolbar">
        <div>
          <h2>Retrieval trace</h2>
          <p className="muted">Inspect how hybrid retrieval ranks chunks before they become chat evidence.</p>
        </div>
        <button type="button" className="secondary" disabled={busy} onClick={onOpenFiles}>
          <FileText size={16} /> Manage file selection <ChevronRight size={14} />
        </button>
      </div>

      {selected.length === 0 ? (
        <div className="trace-empty" role="status">
          <ScanSearch size={28} />
          <p>Select one or more indexed PDFs on the Attached files tab, then return here to trace retrieval.</p>
          <button type="button" className="primary" disabled={busy} onClick={onOpenFiles}>
            Choose files
          </button>
        </div>
      ) : indexedIds.length === 0 ? (
        <div className="trace-empty" role="status">
          <ScanSearch size={28} />
          <p>
            {selected.length} file{selected.length === 1 ? '' : 's'} selected, but none are indexed yet. Docling uploads
            with a ready index are required.
          </p>
          <button type="button" className="secondary" disabled={busy} onClick={onOpenFiles}>
            Review attached files
          </button>
        </div>
      ) : (
        <>
          <section className="trace-selection" aria-label="Indexed files in scope">
            <span className="eyebrow">INDEXED SELECTION</span>
            <ul>
              {selectedNames.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
            <p className="muted small">
              Only these {indexedIds.length} indexed file{indexedIds.length === 1 ? '' : 's'} will be sent to the trace
              endpoint.
            </p>
          </section>

          <form className="trace-form" onSubmit={runTrace}>
            <label className="field">
              Query
              <textarea
                aria-label="Retrieval query"
                placeholder="Ask what you want to retrieve…"
                value={query}
                disabled={running || busy || !topicReady}
                rows={3}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <div className="trace-form-actions">
              <span className="muted small">Top-k: {topK} (from settings)</span>
              <button className="primary" type="submit" disabled={!canRun}>
                {running ? <LoaderCircle className="spin" size={16} /> : <ScanSearch size={16} />}
                Run trace
              </button>
            </div>
          </form>
        </>
      )}

      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}

      {running && (
        <div className="center-state trace-loading" role="status">
          <LoaderCircle className="spin" />
          <p>Loading source chunks and running retrieval trace…</p>
        </div>
      )}

      {result && !running && (
        <div className="trace-results">
          <section className="trace-summary" aria-live="polite">
            <h3>Trace summary</h3>
            <dl>
              <div>
                <dt>Mode</dt>
                <dd>{modeLabel(result.mode)}</dd>
              </div>
              <div>
                <dt>Query</dt>
                <dd>{result.query}</dd>
              </div>
              <div>
                <dt>Evidence hits</dt>
                <dd>{result.hits.length}</dd>
              </div>
            </dl>
            {result.warning && (
              <p className="trace-warning" role="status">
                {result.warning}
              </p>
            )}
          </section>

          <section className="trace-section" aria-labelledby="trace-evidence-title">
            <h3 id="trace-evidence-title">Selected evidence</h3>
            <p className="muted small">Chunks that would be injected into chat, ordered by RRF fusion rank.</p>
            {result.hits.length ? (
              result.hits.map((hit, index) => (
                <HitCard
                  key={hit.chunk_id}
                  hit={hit}
                  file={filesById.get(hit.file_id)}
                  topic={topic}
                  evidenceRank={index + 1}
                />
              ))
            ) : (
              <p className="muted">No evidence chunks were returned for this query.</p>
            )}
          </section>

          {loadedChunks.length > 0 && (
            <section className="trace-section" aria-labelledby="trace-source-title">
              <h3 id="trace-source-title">Source chunks</h3>
              <p className="muted small">All indexed chunks loaded from the selected files for comparison.</p>
              <div className="trace-source-list">
                {loadedChunks.flatMap((entry) => {
                  const file = filesById.get(entry.fileId);
                  if (!file) return [];
                  return entry.chunks.map((chunk, index) => (
                    <SourceChunkCard
                      key={chunk.chunk_id || `${entry.fileId}:${index}`}
                      chunk={chunk}
                      file={file}
                      topic={topic}
                      selected={!!chunk.chunk_id && evidenceIds.has(chunk.chunk_id)}
                    />
                  ));
                })}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
