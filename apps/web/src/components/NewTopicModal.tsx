import { BookOpen, LoaderCircle, Plus, X } from 'lucide-react';

type Props = {
  name: string;
  creating: boolean;
  error: string;
  onChange: (name: string) => void;
  onClose: () => void;
  onSubmit: (event: React.FormEvent) => void;
};

export function NewTopicModal({ name, creating, error, onChange, onClose, onSubmit }: Props) {
  return (
    <div className="modal-backdrop">
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="topic-title">
        <button className="icon-button modal-close" aria-label="Close" disabled={creating} onClick={onClose}>
          <X size={19} />
        </button>
        <span className="hero-icon">
          <BookOpen size={27} />
        </span>
        <h2 id="topic-title">Make room for a new topic</h2>
        <p className="muted">Keep a conversation and its reading in one place.</p>
        <form onSubmit={onSubmit}>
          <label className="field">
            Topic name
            <input
              autoFocus
              required
              maxLength={120}
              placeholder="e.g. Understanding neural networks"
              value={name}
              onChange={(e) => onChange(e.target.value)}
            />
          </label>
          {error && (
            <p role="alert" className="field-error">
              {error}
            </p>
          )}
          <button className="primary" disabled={creating || !name.trim()}>
            {creating ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />} Create topic
          </button>
        </form>
      </section>
    </div>
  );
}
