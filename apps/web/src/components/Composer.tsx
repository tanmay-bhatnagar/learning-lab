import { ArrowDown, ArrowUp, ChevronRight, FileText, Plus, Square } from 'lucide-react';
import type { Model } from '../api/types';
import { modelLabel } from '../modelControls';
import type { ContextMeter as Meter } from '../domain/contextMeter';
import { ContextMeter } from './ContextMeter';
import { ThinkingControl } from './ThinkingControl';

type Props = {
  input: string;
  sending: boolean;
  busy: boolean;
  topicReady: boolean;
  follow: boolean;
  hasMessages: boolean;
  selectedCount: number;
  activeModel?: Model;
  modelError: string;
  meter: Meter;
  bottomRef: React.RefObject<HTMLDivElement | null>;
  thinkValue: (model?: Model) => boolean | string | undefined;
  onInputChange: (value: string) => void;
  onSend: (event: React.FormEvent) => void;
  onStop: () => void;
  onFollowLatest: () => void;
  onOpenFiles: () => void;
  onOpenSettings: () => void;
  onThinkChange: (value: boolean | string, modelId?: string) => void;
  onRetryConnection: () => void;
};

export function Composer({
  input,
  sending,
  busy,
  topicReady,
  follow,
  hasMessages,
  selectedCount,
  activeModel,
  modelError,
  meter,
  bottomRef,
  thinkValue,
  onInputChange,
  onSend,
  onStop,
  onFollowLatest,
  onOpenFiles,
  onOpenSettings,
  onThinkChange,
  onRetryConnection,
}: Props) {
  return (
    <div className="composer-area">
      {!follow && hasMessages && (
        <button
          className="latest-button secondary"
          onClick={() => {
            onFollowLatest();
            bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
          }}
        >
          <ArrowDown size={14} /> Latest
        </button>
      )}
      {modelError && (
        <div className="model-warning">
          Models: {modelError}{' '}
          <button className="text-button" disabled={busy} onClick={onRetryConnection}>
            Retry connection
          </button>
        </div>
      )}
      {selectedCount > 0 && (
        <button className="attachment-summary" onClick={onOpenFiles}>
          <FileText size={14} />
          {selectedCount} {selectedCount === 1 ? 'document' : 'documents'} included
          <ChevronRight size={14} />
        </button>
      )}
      <form className="composer" onSubmit={onSend}>
        <textarea
          aria-label="Message"
          placeholder={
            !activeModel ? 'Choose an available model in settings to start…' : 'Ask anything about this topic…'
          }
          value={input}
          disabled={sending || !topicReady}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div className="composer-tools">
          <div className="composer-options">
            <button type="button" className="icon-button" aria-label="Select attached files" onClick={onOpenFiles}>
              <Plus size={18} />
            </button>
            <span className="tool-divider" />
            <button
              type="button"
              className="model-button"
              aria-label={activeModel ? `Current model: ${modelLabel(activeModel)}` : 'Choose model in settings'}
              disabled={busy}
              onClick={onOpenSettings}
            >
              {activeModel ? modelLabel(activeModel) : 'Choose model'}
            </button>
            <ThinkingControl model={activeModel} busy={busy} thinkValue={thinkValue} onThinkChange={onThinkChange} />
          </div>
          {sending ? (
            <button type="button" className="send-button stop" aria-label="Stop response" onClick={onStop}>
              <Square size={16} />
            </button>
          ) : (
            <button
              className="send-button"
              aria-label="Send message"
              disabled={!input.trim() || !activeModel || busy || !topicReady}
            >
              <ArrowUp size={20} />
            </button>
          )}
        </div>
      </form>
      <div className="composer-footer">
        <span>
          Enter to send <span className="footer-separator">·</span> Shift + Enter for a new line
        </span>
        <ContextMeter meter={meter} />
      </div>
    </div>
  );
}
