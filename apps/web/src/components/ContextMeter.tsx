import type { ContextMeter as Meter } from '../domain/contextMeter';

type Props = {
  meter: Meter;
};

export function ContextMeter({ meter }: Props) {
  return (
    <div className="context" title="Older input drops from model context automatically; saved history remains.">
      <span className="context-track">
        <span style={{ width: `${meter.percent}%` }} />
      </span>
      <span>
        {meter.used === undefined ? 'Context' : `${meter.estimated ? '~' : ''}${meter.used.toLocaleString()} /`}{' '}
        {meter.limit.toLocaleString()}
        {meter.used === undefined ? ' tokens' : ''}
      </span>
    </div>
  );
}
