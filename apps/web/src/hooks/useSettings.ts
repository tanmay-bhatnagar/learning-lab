import { useCallback, useRef, useState } from 'react';
import { api, json } from '../api';
import { settingsSchema, type Context, type Model, type Settings } from '../api/types';
import { modelLabel, modelSelection, validateContext } from '../modelControls';
import { errorText } from '../lib/errors';

export function useSettings(
  settings: Settings,
  setSettings: (value: Settings) => void,
  setParser: (parser: string) => void,
  models: Model[],
  setContext: (value: Context) => void,
  setError: (message: string) => void,
  streamActive: () => boolean,
  uploadLocked: () => boolean,
  busy: () => boolean,
) {
  const [draft, setDraft] = useState<Settings>(settings);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [switching, setSwitching] = useState('');
  const [selectionStatus, setSelectionStatus] = useState('');
  const [selectionError, setSelectionError] = useState('');
  const persistenceLock = useRef(false);

  const syncDraft = useCallback((value: Settings) => {
    setDraft(value);
  }, []);

  const persistSettings = useCallback(
    async (next: Settings, selectedModel?: Model) => {
      if (persistenceLock.current || saving || busy() || streamActive() || uploadLocked()) return;
      const validation = validateContext(next.context_limit);
      if (validation) {
        setError(validation);
        return;
      }
      persistenceLock.current = true;
      setSaving(true);
      setError('');
      setNotice('');
      setSelectionStatus('');
      setSelectionError('');
      if (selectedModel) setSwitching(selectedModel.id);
      try {
        const value = await api('/settings', settingsSchema, json(next, 'PUT'));
        setSettings(value);
        setDraft(value);
        setParser(value.parser);
        if (value.model !== settings.model || value.context_limit !== settings.context_limit) setContext({});
        if (value.model !== next.model)
          throw new Error('The server did not apply the selected model. Please select it again.');
        if (selectedModel) setSelectionStatus(`${modelLabel(selectedModel)} selected. Your next message will use it.`);
        else setNotice('Settings saved. They will apply to your next message.');
      } catch (e) {
        if (selectedModel) setSelectionError(errorText(e));
        else setError(errorText(e));
      } finally {
        persistenceLock.current = false;
        setSaving(false);
        setSwitching('');
      }
    },
    [
      busy,
      setContext,
      setError,
      setParser,
      setSettings,
      settings.context_limit,
      settings.model,
      streamActive,
      uploadLocked,
    ],
  );

  const selectModel = useCallback(
    (id: string) => {
      const model = models.find((m) => m.id === id);
      if (model && id !== settings.model) void persistSettings(modelSelection(settings, model), model);
    },
    [models, persistSettings, settings],
  );

  const saveDraft = useCallback(async () => {
    await persistSettings(draft);
  }, [draft, persistSettings]);

  return {
    draft,
    setDraft,
    syncDraft,
    saving,
    notice,
    setNotice,
    switching,
    selectionStatus,
    selectionError,
    persistenceLock,
    persistSettings,
    selectModel,
    saveDraft,
  };
}
