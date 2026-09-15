import type { Model, Settings } from './api';

export const APP_CONTEXT_MAX = 32768;
export const LEGACY_CONTEXT_LIMIT = 8192;
export const DEFAULT_SETTINGS: Settings = { model: '', context_limit: APP_CONTEXT_MAX, parser: 'anydoc' };

export function modelContextMax(_model?: Model): number {
  return APP_CONTEXT_MAX;
}

export function modelLabel(model: Model | string): string {
  if (typeof model !== 'string' && model.display_name?.trim()) return model.display_name;
  const id = typeof model === 'string' ? model : model.id;
  const [family, tag = ''] = id.split('/').pop()!.split(':');
  const name = family.replace(/^qwen(\d)/i, 'Qwen $1').replace(/^gemma(\d)/i, 'Gemma $1').replace(/^deepseek-r1$/i, 'DeepSeek R1').replace(/^gpt-oss$/i, 'GPT-OSS');
  const parameters = (typeof model !== 'string' ? model.parameter_size : undefined) || tag.match(/(?:^|-)(\d+(?:\.\d+)?b)(?:-|$)/i)?.[1];
  const quantization = (typeof model !== 'string' ? model.quantization : undefined) || tag.match(/q\d+[^:]*/i)?.[0];
  return [name, parameters?.toUpperCase(), quantizationLabel(quantization)].filter(Boolean).join(' · ');
}

export function quantizationLabel(quantization?: string): string | undefined {
  if (!quantization?.trim()) return undefined;
  const bits = quantization.match(/^q(\d+)/i)?.[1];
  return bits ? `${bits}-bit` : undefined;
}

export function normalizeSettings(raw: Partial<Settings>): { settings: Settings; migrated: boolean } {
  const settings: Settings = { ...DEFAULT_SETTINGS, ...raw, context_limit: raw.context_limit ?? APP_CONTEXT_MAX };
  let migrated = false;
  if (settings.context_limit === LEGACY_CONTEXT_LIMIT) {
    settings.context_limit = APP_CONTEXT_MAX;
    migrated = true;
  }
  if (!Number.isInteger(settings.context_limit) || settings.context_limit < 1024 || settings.context_limit > APP_CONTEXT_MAX) {
    settings.context_limit = APP_CONTEXT_MAX;
    migrated = true;
  }
  return { settings, migrated };
}

export function modelSelection(settings: Settings, model: Model): Settings {
  return { ...settings, model: model.id, context_limit: APP_CONTEXT_MAX };
}

export function validateContext(value: number, _model?: Model): string | undefined {
  if (!Number.isInteger(value) || value < 1024 || value > APP_CONTEXT_MAX) {
    return `Context size must be a whole number between 1,024 and ${APP_CONTEXT_MAX.toLocaleString('en-US')}.`;
  }
}

export function thinkingValue(model: Model | undefined, preferences: Record<string, boolean | string>) {
  const capability = model?.thinking;
  if (capability?.type === 'always') return true;
  if (capability?.type === 'toggle') return typeof preferences[model!.id] === 'boolean' ? preferences[model!.id] : false;
  if (capability?.type === 'levels') return capability.levels?.includes(String(preferences[model!.id])) ? preferences[model!.id] : capability.levels?.[0];
  return undefined;
}

export function chatRequest(settings: Settings, model: Model, preferences: Record<string, boolean | string>, message: string, fileIds: string[]) {
  return { message, file_ids: fileIds, model: settings.model, think: thinkingValue(model, preferences), context_limit: settings.context_limit };
}
