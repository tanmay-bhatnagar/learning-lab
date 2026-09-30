import { BookOpen, FlaskConical, MessageSquare, Plus, Settings2 } from 'lucide-react';
import type { Topic } from '../api/types';

type Props = {
  page: 'workspace' | 'settings';
  topics: Topic[];
  topic: string;
  loading: boolean;
  busy: boolean;
  onWorkspace: () => void;
  onSettings: () => void;
  onNewTopic: () => void;
  onSelectTopic: (id: string) => void;
};

export function Sidebar({
  page,
  topics,
  topic,
  loading,
  busy,
  onWorkspace,
  onSettings,
  onNewTopic,
  onSelectTopic,
}: Props) {
  return (
    <aside className="sidebar">
      <a
        className="brand"
        href="#"
        onClick={(e) => {
          e.preventDefault();
          onWorkspace();
        }}
      >
        <span className="brand-icon">
          <FlaskConical size={23} />
        </span>
        <span>
          Learning Lab<small>A SPACE FOR CURIOSITY</small>
        </span>
      </a>
      <div className="sidebar-section">
        <span className="eyebrow">YOUR WORKSPACE</span>
        <button className={`nav-item ${page === 'workspace' ? 'active' : ''}`} onClick={onWorkspace}>
          <MessageSquare size={18} /> Conversations
        </button>
      </div>
      <div className="topic-heading">
        <span className="eyebrow">TOPICS</span>
        <button className="icon-button" aria-label="Create topic" disabled={busy} onClick={onNewTopic}>
          <Plus size={17} />
        </button>
      </div>
      <div className="topic-list">
        {topics.map((t) => (
          <button
            key={t.id}
            className={`topic-item ${topic === t.id ? 'selected' : ''}`}
            disabled={busy}
            onClick={() => onSelectTopic(t.id)}
          >
            <BookOpen size={16} />
            <span>{t.name}</span>
            {topic === t.id && <span className="active-dot" />}
          </button>
        ))}
        {!loading && !topics.length && (
          <p className="sidebar-empty">Give your next question a home. Create a topic to begin.</p>
        )}
      </div>
      <button className="new-topic" disabled={busy} onClick={onNewTopic}>
        <Plus size={17} /> New topic
      </button>
      <div className="sidebar-bottom">
        <div className="local-note">
          <span className="status-dot" />
          <span>
            Local workspace<small>Your topics. Your models.</small>
          </span>
        </div>
        <button className={`nav-item ${page === 'settings' ? 'active' : ''}`} onClick={onSettings}>
          <Settings2 size={18} /> Settings
        </button>
      </div>
    </aside>
  );
}
