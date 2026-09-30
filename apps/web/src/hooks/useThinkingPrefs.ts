import { useCallback, useEffect, useState } from 'react';
import { parsePayload, thinkingPrefsSchema } from '../api/types';

const STORAGE_KEY = 'lab-thinking';

function readThinkingPrefs(): Record<string, boolean | string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    const result = thinkingPrefsSchema.safeParse(parsed);
    if (!result.success) return {};
    return result.data;
  } catch {
    /* ignore corrupt localStorage */
    return {};
  }
}

export function writeThinkingPrefs(value: Record<string, boolean | string>): void {
  try {
    parsePayload(thinkingPrefsSchema, value, 'thinking preferences');
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* quota or private mode — prefs stay in memory for this session */
  }
}

export function useThinkingPrefs() {
  const [thinking, setThinking] = useState<Record<string, boolean | string>>(readThinkingPrefs);
  const [storageError, setStorageError] = useState('');

  useEffect(() => {
    try {
      parsePayload(thinkingPrefsSchema, thinking, 'thinking preferences');
      localStorage.setItem(STORAGE_KEY, JSON.stringify(thinking));
      setStorageError('');
    } catch {
      setStorageError('Thinking preferences could not be saved in this browser.');
    }
  }, [thinking]);

  const setThink = useCallback((value: boolean | string, modelId: string) => {
    setThinking((previous) => ({ ...previous, [modelId]: value }));
  }, []);

  return { thinking, setThink, storageError };
}
