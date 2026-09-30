import type { Context, Settings } from '../api/types';

export type ContextMeter = {
  limit: number;
  used?: number;
  estimated?: boolean;
  percent: number;
  label: string;
};

export function contextMeter(context: Context, settings: Settings): ContextMeter {
  const limit = context.limit || settings.context_limit;
  const used = context.used;
  const percent = Math.min(100, Math.max(0, ((used || 0) / limit) * 100));
  const label =
    used === undefined
      ? 'Context tokens'
      : `${context.estimated ? '~' : ''}${used.toLocaleString()} / ${limit.toLocaleString()}`;
  return { limit, used, estimated: context.estimated, percent, label };
}
