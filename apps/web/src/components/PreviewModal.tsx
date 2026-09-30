import { ExternalLink, FileText, LoaderCircle, X } from 'lucide-react';
import { fileOriginalPath } from '../api';
import type { LabFile } from '../api/types';
import { RichText } from './RichText';

type Props = {
  topic: string;
  file: LabFile;
  tab: 'markdown' | 'original';
  markdown: string;
  loading: boolean;
  error: string;
  onTab: (tab: 'markdown' | 'original') => void;
  onClose: () => void;
};

export function PreviewModal({ topic, file, tab, markdown, loading, error, onTab, onClose }: Props) {
  return (
    <div className="modal-backdrop">
      <section className="preview-modal" role="dialog" aria-modal="true" aria-label={`Inspect ${file.name}`}>
        <div className="preview-header">
          <FileText size={20} />
          <strong>{file.name}</strong>
          <button className="icon-button" aria-label="Close preview" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        <div className="tabs">
          <button className={tab === 'markdown' ? 'active' : ''} onClick={() => onTab('markdown')}>
            Parsed Markdown
          </button>
          <button className={tab === 'original' ? 'active' : ''} onClick={() => onTab('original')}>
            Original PDF
          </button>
          <a
            className="original-link"
            target="_blank"
            rel="noopener noreferrer"
            href={`/api${fileOriginalPath(topic, file.id)}`}
          >
            Open PDF <ExternalLink size={13} />
          </a>
        </div>
        <div className="preview-content">
          {tab === 'original' ? (
            <iframe title={`Original PDF: ${file.name}`} src={`/api${fileOriginalPath(topic, file.id)}`} />
          ) : loading ? (
            <div className="center-state">
              <LoaderCircle className="spin" />
              Loading Markdown…
            </div>
          ) : error ? (
            <p role="alert" className="field-error">
              {error}
            </p>
          ) : markdown ? (
            <RichText text={markdown} />
          ) : (
            <p className="muted">No Markdown content is available yet.</p>
          )}
        </div>
      </section>
    </div>
  );
}
