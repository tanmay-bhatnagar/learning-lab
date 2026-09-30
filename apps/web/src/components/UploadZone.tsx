import { LoaderCircle, Upload } from 'lucide-react';

type Props = {
  uploading: boolean;
  dragging: boolean;
  dropBlocked: boolean;
  busy: boolean;
  topicReady: boolean;
  dropFeedback: string;
  onClick: () => void;
};

export function UploadZone({ uploading, dragging, dropBlocked, busy, topicReady, dropFeedback, onClick }: Props) {
  return (
    <>
      <button
        type="button"
        className={`upload-zone ${dragging ? 'dragging' : ''} ${dropBlocked ? 'drop-rejected' : ''}`}
        disabled={busy || !topicReady}
        onClick={onClick}
        aria-describedby={dropFeedback ? 'drop-feedback' : undefined}
      >
        {uploading ? <LoaderCircle className="spin" size={26} /> : <Upload size={26} />}
        <strong>
          {uploading
            ? 'Uploading & parsing your PDF…'
            : dropBlocked
              ? 'PDFs only — fix the issue below'
              : dragging
                ? 'Release to add your PDFs'
                : 'Drop PDFs here or click to browse'}
        </strong>
        <span>PDF files up to 25 MiB each. Originals stay alongside their parsed Markdown.</span>
      </button>
      {dropFeedback && (
        <p id="drop-feedback" role="alert" className="drop-feedback">
          {dropFeedback}
        </p>
      )}
    </>
  );
}
