import { Sparkles } from 'lucide-react';
import type { Model } from '../api/types';

type Props = {
  model?: Model;
  busy: boolean;
  thinkValue: (model?: Model) => boolean | string | undefined;
  onThinkChange: (value: boolean | string, modelId?: string) => void;
};

export function ThinkingControl({ model, busy, thinkValue, onThinkChange }: Props) {
  const kind = model?.thinking?.type;
  if (!kind || kind === 'none') return <span className="muted small">Standard response</span>;
  if (kind === 'always')
    return (
      <span className="thinking-pill">
        <Sparkles size={13} /> Always thinking
      </span>
    );
  if (kind === 'toggle')
    return (
      <label className="thinking-pill">
        <input
          type="checkbox"
          checked={thinkValue(model) === true}
          onChange={(e) => onThinkChange(e.target.checked, model?.id)}
          disabled={busy}
        />
        <Sparkles size={13} /> Thinking {thinkValue(model) === true ? 'On' : 'Off'}
      </label>
    );
  if (kind === 'levels' && model?.thinking.levels?.length)
    return (
      <label className="thinking-pill">
        <Sparkles size={13} />
        <span>Thinking</span>
        <select
          aria-label="Thinking level"
          value={String(thinkValue(model) || '')}
          disabled={busy}
          onChange={(e) => onThinkChange(e.target.value, model.id)}
        >
          {model.thinking.levels.map((level) => (
            <option key={level}>{level}</option>
          ))}
        </select>
      </label>
    );
  return <span className="muted small">Standard response</span>;
}
