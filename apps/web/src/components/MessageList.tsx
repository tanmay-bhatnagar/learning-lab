import { BookOpen, ChevronRight, FlaskConical, LoaderCircle, Sparkles } from 'lucide-react';
import type { LabFile, Message, Model } from '../api/types';
import { modelLabel } from '../modelControls';
import { MessageSources } from '../citations';
import { originalPdfUrl } from '../api/urls';
import { RichText } from './RichText';
import { PrerequisiteSnapshot } from './PrerequisiteSnapshot';

type Props = {
  messages: Message[];
  models: Model[];
  topic: string;
  files: LabFile[];
  sending: boolean;
  bottomRef: React.RefObject<HTMLDivElement | null>;
  onStarterPrompt: (text: string) => void;
};

export function MessageList({ messages, models, topic, files, sending, bottomRef, onStarterPrompt }: Props) {
  if (!messages.length) {
    return (
      <div className="chat-empty">
        <span className="hero-icon">
          <Sparkles size={30} />
        </span>
        <span className="eyebrow">ROOM TO THINK</span>
        <h2>Follow your curiosity.</h2>
        <p>
          Ask a question, explore an idea, or make sense of your reading.
          <br />
          Everything here stays with this topic.
        </p>
        <div className="starter-grid">
          {[
            { label: 'Explain a concept step by step', prompt: 'Explain this concept step by step: ' },
            { label: 'Help me explore a question', prompt: 'Help me explore this question: ' },
            {
              label: 'Find connections in my reading',
              prompt: 'Find connections in the selected reading, focusing on: ',
            },
          ].map(({ label, prompt }) => (
            <button key={label} onClick={() => onStarterPrompt(prompt)}>
              <BookOpen size={17} />
              <span>{label}</span>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="message-list">
      {messages.map((message, i) => (
        <article className={`message ${message.role === 'user' ? 'user' : 'assistant'}`} key={i}>
          <div className="message-avatar">{message.role === 'user' ? 'Y' : <FlaskConical size={17} />}</div>
          <div className="message-body">
            <div className="message-author">
              {message.role === 'user' ? 'You' : message.role === 'assistant' ? 'Learning Lab' : message.role}
              {message.role === 'assistant' && message.model && (
                <span className="message-model">
                  {modelLabel(models.find((m) => m.id === message.model) || message.model)}
                </span>
              )}
            </div>
            {message.thinking && (
              <details className="thinking-block" open={sending && i === messages.length - 1 && !message.content}>
                <summary>
                  <Sparkles size={13} /> Thinking
                </summary>
                <RichText text={message.thinking} />
              </details>
            )}
            {message.content && <RichText text={message.content} />}{' '}
            {message.prerequisite_import && (
              <PrerequisiteSnapshot metadata={message.prerequisite_import} topic={topic} files={files} />
            )}
            {message.summary_import && (
              <div className="summary-import-meta">
                {(() => {
                  const metadata = message.summary_import;
                  const sourceFile = files.find((file) => file.id === metadata.file_id);
                  return (
                    <>
                      <strong>Generated section summary</strong>
                      <span>{metadata.section_title}</span>
                      <span>{metadata.model}</span>
                      <time dateTime={metadata.summary_created_at}>
                        {new Date(metadata.summary_created_at).toLocaleString()}
                      </time>
                      <span>Snapshot added to this conversation; it is not verbatim document text.</span>
                      <div className="map-pages" aria-label="Imported summary sources">
                        {metadata.sources.map((source) => {
                          const validPages = source.pages.filter(
                            (page) =>
                              page > 0 &&
                              sourceFile?.status === 'ready' &&
                              (sourceFile.page_count == null || page <= sourceFile.page_count),
                          );
                          return (
                            <span className="summary-import-source" key={source.label}>
                              <strong>[{source.label}]</strong>
                              {validPages.map((page) => (
                                <a
                                  key={page}
                                  href={originalPdfUrl(topic, metadata.file_id, page)}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  Page {page}
                                </a>
                              ))}
                              {source.pages.length === 0 && <span>Page unknown</span>}
                              {source.pages.length > validPages.length && source.pages.length > 0 && (
                                <span>Page unavailable</span>
                              )}
                            </span>
                          );
                        })}
                      </div>
                    </>
                  );
                })()}
              </div>
            )}
            {!message.content && sending && i === messages.length - 1 && (
              <div className="generating">
                <LoaderCircle className="spin" size={14} /> {message.thinking ? 'Reasoning…' : 'Waiting for model…'}
              </div>
            )}
            {message.incomplete && <span className="interrupted">Response incomplete</span>}
            {message.role === 'assistant' && (
              <MessageSources topic={topic} files={files} retrieval={message.retrieval} />
            )}
          </div>
        </article>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
