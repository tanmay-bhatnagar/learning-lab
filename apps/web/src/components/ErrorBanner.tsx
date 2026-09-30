import { X } from 'lucide-react';

export function ErrorBanner({
  message,
  busy,
  loading,
  onReload,
  onDismiss,
}: {
  message: string;
  busy: boolean;
  loading: boolean;
  onReload: () => void;
  onDismiss: () => void;
}) {
  if (!message) return null;
  return (
    <div className="banner error" role="alert">
      <span>{message}</span>
      <button disabled={busy || loading} onClick={onReload}>
        Reload
      </button>
      <button className="icon-button" aria-label="Dismiss error" onClick={onDismiss}>
        <X size={15} />
      </button>
    </div>
  );
}
