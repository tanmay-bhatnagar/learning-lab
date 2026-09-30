import { useCallback, useEffect, useRef, useState } from 'react';
import { api, json } from '../api/client';
import { settingsSchema, type Context, type Model, type Settings } from '../api/types';
import { modelLabel, modelSelection, validateContext } from '../modelControls';
import { errorText } from '../lib/errors';
import { isBusy, type Activity } from '../state/activity';
import type { useActivity } from './useActivity';

type ActivityApi = Pick<ReturnType<typeof useActivity>, 'begin' | 'end'>;

export function useSettings(
  settings: Settings,
  setSettings: (value: Settings) => void,
  setParser: (parser: string) => void,
  models: Model[],
  setContext: (value: Context) => void,
  setError: (message: string) => void,
  activity: Activity,
  activityApi: ActivityApi,
) {
  const [draft, setDraft] = useState(settings);
  const [trackedSettings, setTrackedSettings] = useState(settings);
  const [notice, setNotice] = useState('');
  const [switching, setSwitching] = useState('');
  const [selectionStatus, setSelectionStatus] = useState('');
  const [selectionError, setSelectionError] = useState('');
  const settingsRef = useRef(settings);
  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);
  if (settings !== trackedSettings) {
    setTrackedSettings(settings);
    setDraft(settings);
  }

  const persistSettings = useCallback(
    async (next: Settings, selectedModel?: Model) => {
      const op = selectedModel ? 'selectModel' : 'saveSettings';
      if (isBusy(activity) || activity === 'creatingTopic') return;
      const validation = validateContext(next.context_limit);
      if (validation) {
        setError(validation);
        return;
      }
      if (!activityApi.begin(op)) return;
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
        if (value.model !== settingsRef.current.model || value.context_limit !== settingsRef.current.context_limit) {
          setContext({});
        }
        if (value.model !== next.model)
          throw new Error('The server did not apply the selected model. Please select it again.');
        if (selectedModel) setSelectionStatus(`${modelLabel(selectedModel)} selected. Your next message will use it.`);
        else setNotice('Settings saved. They will apply to your next message.');
      } catch (e) {
        if (selectedModel) setSelectionError(errorText(e));
        else setError(errorText(e));
      } finally {
        setSwitching('');
        activityApi.end();
      }
    },
    [activity, activityApi, setContext, setError, setParser, setSettings],
  );

  const selectModel = useCallback(
    (id: string) => {
      const model = models.find((m) => m.id === id);
      if (model && id !== settingsRef.current.model)
        void persistSettings(modelSelection(settingsRef.current, model), model);
    },
    [models, persistSettings],
  );

  const saveDraft = useCallback(
    async (event?: React.FormEvent) => {
      event?.preventDefault();
      await persistSettings(draft);
    },
    [draft, persistSettings],
  );

  return {
    draft,
    setDraft,
    notice,
    setNotice,
    switching,
    selectionStatus,
    selectionError,
    selectModel,
    saveDraft,
  };
}
