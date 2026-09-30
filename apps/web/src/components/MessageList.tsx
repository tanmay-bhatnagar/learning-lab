import { BookOpen, ChevronRight, FlaskConical, LoaderCircle, Sparkles } from 'lucide-react';
import type { LabFile, Message, Model } from '../api/types';
import { modelLabel } from '../modelControls';
import { MessageSources } from '../citations';
import { RichText } from './RichText';

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
