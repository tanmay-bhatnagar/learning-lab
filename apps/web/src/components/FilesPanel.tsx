import type { DragEvent, RefObject } from 'react';
import type { LabFile } from '../api/types';
import { parserOptions } from './parserOptions';
import { FileRow } from './FileRow';
import { UploadZone } from './UploadZone';

type Props = {
  files: LabFile[];
  selected: string[];
  parser: string;
  busy: boolean;
  topicReady: boolean;
  uploading: boolean;
  dragging: boolean;
  dropBlocked: boolean;
  dropFeedback: string;
  uploadBlocked: string | null;
  dragDepthRef: RefObject<number>;
  onParserChange: (parser: string) => void;
  onToggleFile: (fileId: string, checked: boolean) => void;
  onInspect: (file: LabFile) => void;
  onUploadClick: () => void;
  onDrop: (files: FileList) => void;
  setDragging: (dragging: boolean) => void;
  setDropBlocked: (blocked: boolean) => void;
  showDropFeedback: (reason: string) => void;
  onReturnToChat: () => void;
  onRefreshFiles: () => void;
};

export function FilesPanel({
  files,
  selected,
  parser,
  busy,
  topicReady,
  uploading,
  dragging,
  dropBlocked,
  dropFeedback,
  uploadBlocked,
  dragDepthRef,
  onParserChange,
  onToggleFile,
  onInspect,
  onUploadClick,
  onDrop,
  setDragging,
  setDropBlocked,
  showDropFeedback,
  onReturnToChat,
  onRefreshFiles,
}: Props) {
  const handleDragEnter = (e: DragEvent) => {
    if (!Array.from(e.dataTransfer.types).includes('Files')) return;
    e.preventDefault();
    dragDepthRef.current += 1;
    const blocked = !!uploadBlocked;
    setDropBlocked(blocked);
    setDragging(!blocked);
    if (blocked && uploadBlocked) showDropFeedback(uploadBlocked);
  };

  const handleDragOver = (e: DragEvent) => {
    if (!Array.from(e.dataTransfer.types).includes('Files')) return;
    e.preventDefault();
    e.stopPropagation();
    const blocked = !!uploadBlocked;
    setDropBlocked(blocked);
    e.dataTransfer.dropEffect = blocked ? 'none' : 'copy';
  };

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (!dragDepthRef.current) {
      setDragging(false);
      setDropBlocked(false);
    }
  };

  return (
    <div
      className={`files-page ${dragging ? 'dragging' : ''} ${dropBlocked ? 'drop-rejected' : ''}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragging(false);
        dragDepthRef.current = 0;
        onDrop(e.dataTransfer.files);
      }}
    >
      <div className="files-toolbar">
        <div>
          <h2>Your reading material</h2>
          <p className="muted">
            Drag PDFs into this page or click below to browse. Select documents to include in your next message.
          </p>
        </div>
        <label className="parser-select">
          PDF parser
          <select value={parser} disabled={busy} onChange={(e) => onParserChange(e.target.value)}>
            {parserOptions}
          </select>
        </label>
      </div>
      <UploadZone
        uploading={uploading}
        dragging={dragging}
        dropBlocked={dropBlocked}
        busy={busy}
        topicReady={topicReady}
        dropFeedback={dropFeedback}
        onClick={onUploadClick}
      />
      <div className="file-list">
        {files.map((file) => (
          <FileRow
            key={file.id}
            file={file}
            selected={selected.includes(file.id)}
            busy={busy}
            topicReady={topicReady}
            onToggle={(checked) => onToggleFile(file.id, checked)}
            onInspect={() => onInspect(file)}
          />
        ))}
      </div>
      {files.length > 0 && (
        <div className="files-footer">
          <span>{selected.length} selected for your next message</span>
          <button className="text-button" onClick={onReturnToChat}>
            Return to conversation →
          </button>
          <button className="text-button" disabled={busy} onClick={onRefreshFiles}>
            Refresh files
          </button>
        </div>
      )}
    </div>
  );
}
