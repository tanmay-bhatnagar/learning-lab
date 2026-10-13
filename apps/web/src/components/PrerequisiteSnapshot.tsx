import type { LabFile, PrerequisiteImportMetadata } from '../api/types';
import { originalPdfUrl } from '../api/urls';

type Props = {
  metadata: PrerequisiteImportMetadata;
  topic: string;
  files: LabFile[];
};

function readableDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function PrerequisiteSnapshot({ metadata, topic, files }: Props) {
  const sourceFile = metadata.topic_id === topic ? files.find((file) => file.id === metadata.file_id) : undefined;
  const knownPageCount =
    sourceFile?.status === 'ready' && Number.isInteger(sourceFile.page_count) && (sourceFile.page_count ?? 0) >= 0;

  return (
    <section className="summary-import-meta prerequisite-snapshot" aria-label="Prerequisite snapshot">
      <strong>Generated prerequisite snapshot</strong>
      <span>{metadata.section_title}</span>
      <span>{metadata.goal || 'No learning goal was recorded.'}</span>
      <span>{metadata.model}</span>
      <time dateTime={metadata.assessment_finished_at}>Generated {readableDate(metadata.assessment_finished_at)}</time>
      <time dateTime={metadata.imported_at}>Added {readableDate(metadata.imported_at)}</time>
      <span>
        These are model-inferred suggestions, not verified prerequisites or proof of mastery. Comfort answers shown in
        this message are the historical answers captured when the snapshot was added; later answers do not rewrite it.
      </span>
      <div className="map-pages" aria-label="Prerequisite snapshot sources">
        {metadata.sources.map((source) => {
          const pages = [...new Set(source.pages)].sort((left, right) => left - right);
          return (
            <span className="summary-import-source" key={`${source.label}-${source.unit_id}`}>
              <strong>[{source.label}]</strong>
              {pages.length === 0 && <span>Page target unavailable</span>}
              {pages.map((page) => {
                const pageIsSafe =
                  Number.isInteger(page) && page > 0 && knownPageCount && page <= (sourceFile?.page_count ?? 0);
                return pageIsSafe ? (
                  <a key={page} href={originalPdfUrl(topic, metadata.file_id, page)} target="_blank" rel="noreferrer">
                    Page {page}
                  </a>
                ) : (
                  <span key={page}>Page {page} unavailable</span>
                );
              })}
            </span>
          );
        })}
      </div>
    </section>
  );
}
