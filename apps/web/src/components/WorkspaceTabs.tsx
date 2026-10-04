import { FileText, Map, MessageSquare, ScanSearch } from 'lucide-react';

type Tab = 'chat' | 'files' | 'trace' | 'map';

type Props = {
  tab: Tab;
  fileCount: number;
  onTab: (tab: Tab) => void;
};

export function WorkspaceTabs({ tab, fileCount, onTab }: Props) {
  return (
    <div className="tabs">
      <button className={tab === 'chat' ? 'active' : ''} onClick={() => onTab('chat')}>
        <MessageSquare size={16} /> Conversation
      </button>
      <button className={tab === 'files' ? 'active' : ''} onClick={() => onTab('files')}>
        <FileText size={16} /> Attached files <span className="count">{fileCount}</span>
      </button>
      <button className={tab === 'trace' ? 'active' : ''} onClick={() => onTab('trace')}>
        <ScanSearch size={16} /> Retrieval trace
      </button>
      <button className={tab === 'map' ? 'active' : ''} onClick={() => onTab('map')}>
        <Map size={16} /> Map
      </button>
    </div>
  );
}
