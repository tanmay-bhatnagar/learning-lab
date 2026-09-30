import { ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-react';

type Props = {
  sidebar: boolean;
  pageTitle: string;
  onToggleSidebar: () => void;
};

export function TopBar({ sidebar, pageTitle, onToggleSidebar }: Props) {
  return (
    <header className="topbar">
      <div className="breadcrumbs">
        <button
          className="icon-button"
          aria-label={sidebar ? 'Hide sidebar' : 'Show sidebar'}
          onClick={onToggleSidebar}
        >
          {sidebar ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
        </button>
        <span>Workspace</span>
        <ChevronRight size={14} />
        <strong>{pageTitle}</strong>
      </div>
      <span className="local-badge">LOCAL MODELS</span>
    </header>
  );
}
