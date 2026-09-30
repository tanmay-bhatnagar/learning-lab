import { ChevronRight, FileText } from 'lucide-react';
import type { LabFile } from '../api/types';
import { fileMeta, isSelectable, showLegacyUnassessedWarning } from '../domain/files';

type Props = {
  file: LabFile;
  selected: boolean;
  busy: boolean;
  topicReady: boolean;
  onToggle: (checked: boolean) => void;
  onInspect: () => void;
};

export function FileRow({ file, selected, busy, topicReady, onToggle, onInspect }: Props) {
  return (
    <div className="file-row">
      <input
        type="checkbox"
        aria-label={`Include ${file.name} in chat`}
        checked={selected}
        disabled={busy || !topicReady || !isSelectable(file)}
        onChange={(e) => onToggle(e.target.checked)}
      />
      <span className="file-icon">
        <FileText size={23} />
      </span>
      <div className="file-details">
        <strong>{file.name}</strong>
        <span>{fileMeta(file)}</span>
        {file.extraction_diagnostics && (
          <p className={`extraction-diagnostic ${file.extraction_diagnostics.status}`} role="status">
            <strong>Extraction: {file.extraction_diagnostics.status.replace('_', ' ')}.</strong>{' '}
            {file.extraction_diagnostics.note}
            {file.extraction_diagnostics.findings.length > 0 && (
              <ul>
                {file.extraction_diagnostics.findings.map((finding, index) => (
                  <li key={index}>{finding}</li>
                ))}
              </ul>
            )}
          </p>
        )}
        {showLegacyUnassessedWarning(file) && (
          <p className="field-error" role="status">
            Extraction fidelity unassessed for this saved record.
          </p>
        )}
        {file.warnings?.map((warning, index) => (
          <p key={index} className="field-error" role="status">
            {warning}
          </p>
        ))}
        {file.error && <p className="field-error">{file.error}</p>}
      </div>
      <button className="secondary" onClick={onInspect}>
        Inspect <ChevronRight size={14} />
      </button>
    </div>
  );
}
