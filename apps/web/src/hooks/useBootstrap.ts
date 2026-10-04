import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { modelsResponseSchema, settingsSchema, topicsResponseSchema } from '../api/types';
import type { Model, Settings, Topic } from '../api/types';
import { DEFAULT_SETTINGS, normalizeSettings } from '../modelControls';
import { errorText } from '../lib/errors';

export function useBootstrap() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [topic, setTopic] = useState('');
  const [models, setModels] = useState<Model[]>([]);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [settingsReady, setSettingsReady] = useState(false);
  const [parser, setParser] = useState(DEFAULT_SETTINGS.parser);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modelError, setModelError] = useState('');
  const [settingsError, setSettingsError] = useState('');
  const modelRequest = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      modelRequest.current += 1;
    };
  }, []);

  const refreshModels = useCallback(async () => {
    const request = ++modelRequest.current;
    setModelError('');
    try {
      const result = await api('/models', modelsResponseSchema);
      if (!mounted.current || request !== modelRequest.current) return;
      setModels(result.models);
      setModelError(result.error || '');
    } catch (e) {
      if (!mounted.current || request !== modelRequest.current) return;
      setModelError(errorText(e));
    }
  }, []);

  const initialize = useCallback(async () => {
    const modelRequestId = ++modelRequest.current;
    setLoading(true);
    setSettingsReady(false);
    setError('');
    const results = await Promise.allSettled([
      api('/topics', topicsResponseSchema),
      api('/models', modelsResponseSchema),
      api('/settings', settingsSchema),
    ]);
    const [t, m, s] = results;
    if (t.status === 'fulfilled') {
      setTopics(t.value.topics);
      setTopic((current) => current || t.value.topics[0]?.id || '');
    } else setError(errorText(t.reason));
    if (m.status === 'fulfilled' && mounted.current && modelRequestId === modelRequest.current) {
      setModels(m.value.models);
      setModelError(m.value.error || '');
    } else if (m.status === 'rejected' && mounted.current && modelRequestId === modelRequest.current) {
      setModelError(errorText(m.reason));
    }
    if (s.status === 'fulfilled') {
      const { settings: value } = normalizeSettings(s.value);
      setSettings(value);
      setParser(value.parser);
      setSettingsError('');
      setSettingsReady(true);
    } else setSettingsError(`Could not load settings: ${errorText(s.reason)}`);
    setLoading(false);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount bootstrap must trigger one async load
    void initialize();
  }, [initialize]);

  return {
    topics,
    setTopics,
    topic,
    setTopic,
    models,
    settings,
    settingsReady,
    setSettings,
    parser,
    setParser,
    loading,
    error,
    setError,
    modelError,
    settingsError,
    migrationError: settingsError,
    refreshModels,
    initialize,
  };
}
