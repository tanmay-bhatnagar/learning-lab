import { useCallback, useEffect, useRef, useState } from 'react';
import { api, json } from '../api';
import { modelsResponseSchema, settingsSchema, topicsResponseSchema } from '../api/types';
import type { Model, Settings, Topic } from '../api/types';
import { DEFAULT_SETTINGS, normalizeSettings } from '../modelControls';
import { errorText } from '../lib/errors';

export function useBootstrap() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [topic, setTopic] = useState('');
  const [models, setModels] = useState<Model[]>([]);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [parser, setParser] = useState(DEFAULT_SETTINGS.parser);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modelError, setModelError] = useState('');
  const [migrationError, setMigrationError] = useState('');
  const migrationLock = useRef(false);

  const refreshModels = useCallback(async () => {
    setModelError('');
    try {
      const result = await api('/models', modelsResponseSchema);
      setModels(result.models);
      setModelError(result.error || '');
    } catch (e) {
      setModelError(errorText(e));
    }
  }, []);

  const initialize = useCallback(async () => {
    setLoading(true);
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
    if (m.status === 'fulfilled') {
      setModels(m.value.models);
      setModelError(m.value.error || '');
    } else setModelError(errorText(m.reason));
    if (s.status === 'fulfilled') {
      const { settings: value, migrated } = normalizeSettings(s.value);
      setSettings(value);
      setParser(value.parser);
      if (migrated && !migrationLock.current) {
        migrationLock.current = true;
        api('/settings', settingsSchema, json(value, 'PUT'))
          .then((saved) => {
            setSettings(saved);
            setParser(saved.parser);
          })
          .catch((e) => setMigrationError(errorText(e)))
          .finally(() => {
            migrationLock.current = false;
          });
      }
    } else setError(errorText(s.reason));
    setLoading(false);
  }, []);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  return {
    topics,
    setTopics,
    topic,
    setTopic,
    models,
    settings,
    setSettings,
    parser,
    setParser,
    loading,
    error,
    setError,
    modelError,
    migrationError,
    refreshModels,
    initialize,
  };
}
