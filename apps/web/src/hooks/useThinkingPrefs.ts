import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'lab-thinking';

function readThinkingPrefs(): Record<string, boolean | string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return {};
    return parsed as Record<string, boolean | string>;
  } catch {
    /* ignore corrupt localStorage */
    return {};
  }
}

function writeThinkingPrefs(value: Record<string, boolean | string>): void {
  try {
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
      localStorage.setItem(STORAGE_KEY, JSON.stringify(thinking));
      setStorageError('');
    } catch {
      /* quota or private mode */
      setStorageError('Thinking preferences could not be saved in this browser.');
    }
  }, [thinking]);

  const setThink = useCallback((value: boolean | string, modelId: string) => {
    setThinking((previous) => ({ ...previous, [modelId]: value }));
  }, []);

  return { thinking, setThink, storageError };
}

export { writeThinkingPrefs, readThinkingPrefs };
