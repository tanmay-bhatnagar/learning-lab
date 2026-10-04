import { useState } from 'react';
import type { Conversation } from '../api/types';

type Props = {
  conversations: Conversation[];
  activeId: string;
  disabled: boolean;
  onSelect: (id: string) => void;
  onCreate: (title: string) => void;
  onRename: (id: string, title: string) => void;
};

export function ConversationBar({ conversations, activeId, disabled, onSelect, onCreate, onRename }: Props) {
  const [mode, setMode] = useState<'create' | 'rename' | null>(null);
  const [title, setTitle] = useState('');
  const active = conversations.find((item) => item.id === activeId);

  return (
    <div className="conversation-bar">
      <label htmlFor="conversation-picker">Conversation</label>
      <select
        id="conversation-picker"
        value={activeId}
        disabled={disabled}
        onChange={(event) => onSelect(event.target.value)}
      >
        {conversations.map((item) => (
          <option key={item.id} value={item.id}>
            {item.title}
          </option>
        ))}
      </select>
      <button
        className="secondary"
        disabled={disabled}
        onClick={() => {
          setTitle('');
          setMode('create');
        }}
      >
        New chat
      </button>
      <button
        className="secondary"
        disabled={disabled || !active}
        onClick={() => {
          setTitle(active?.title || '');
          setMode('rename');
        }}
      >
        Rename
      </button>
      {mode && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (disabled || !title.trim()) return;
            if (mode === 'create') onCreate(title.trim());
            else onRename(activeId, title.trim());
            setMode(null);
          }}
        >
          <input
            aria-label="Conversation title"
            autoFocus
            disabled={disabled}
            maxLength={100}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <button type="submit" disabled={disabled || !title.trim()}>
            Save
          </button>
          <button type="button" disabled={disabled} onClick={() => setMode(null)}>
            Cancel
          </button>
        </form>
      )}
    </div>
  );
}
