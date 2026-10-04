import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { documentMapResponseSchema, type DocumentMapResponse } from '../api/documentMap';
import { filePath } from '../api/urls';
import { aborted, errorText } from '../lib/errors';
import type { LabFile } from '../api/types';
import type { Activity } from '../state/activity';
import type { useActivity } from './useActivity';

type ActivityApi = Pick<ReturnType<typeof useActivity>, 'begin' | 'end'>;
type State = { topic: string; fileId: string; response: DocumentMapResponse | null; loading: boolean; error: string };
const emptyState: State = { topic: '', fileId: '', response: null, loading: false, error: '' };

export function useDocumentMap(
  topic: string,
  files: LabFile[],
  enabled: boolean,
  activity: Activity,
  activityApi: ActivityApi,
) {
  const [selection, setSelection] = useState({ topic, fileId: '' });
  const fileId = selection.topic === topic ? selection.fileId : '';
  const [state, setState] = useState<State>(emptyState);
  const revision = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const responseRef = useRef<DocumentMapResponse | null>(null);
  const currentTopic = useRef(topic);
  const selectedFile = files.find((file) => file.id === fileId);

  const load = useCallback(
    async (force = false) => {
      if (!enabled || !topic || !fileId) return;
      controller.current?.abort();
      const requestController = new AbortController();
      controller.current = requestController;
      const requestRevision = ++revision.current;
      setState({ topic, fileId, response: force ? null : responseRef.current, loading: true, error: '' });
      try {
        const response = await api(`${filePath(topic, fileId)}/map`, documentMapResponseSchema, {
          signal: requestController.signal,
        });
        if (requestController.signal.aborted || requestRevision !== revision.current || currentTopic.current !== topic)
          return;
        responseRef.current = response;
        setState({ topic, fileId, response, loading: false, error: '' });
      } catch (error) {
        if (aborted(error) || requestRevision !== revision.current || currentTopic.current !== topic) return;
        setState({ topic, fileId, response: null, loading: false, error: errorText(error) });
      }
    },
    [enabled, fileId, topic],
  );

  useEffect(() => {
    currentTopic.current = topic;
  }, [topic]);

  useEffect(() => {
    revision.current += 1;
    controller.current?.abort();
    controller.current = null;
    responseRef.current = null;
  }, [topic]);

  useEffect(() => {
    if (!enabled || !fileId || !selectedFile) return;
    void load(true);
    return () => {
      revision.current += 1;
      controller.current?.abort();
      controller.current = null;
    };
  }, [enabled, fileId, selectedFile, load]);

  const build = useCallback(async () => {
    if (!topic || !fileId || !enabled || !selectedFile || activity !== 'idle') return;
    if (!activityApi.begin('buildMap')) return;
    controller.current?.abort();
    const requestController = new AbortController();
    controller.current = requestController;
    const requestRevision = ++revision.current;
    setState({ topic, fileId, response: responseRef.current, loading: true, error: '' });
    try {
      const response = await api(`${filePath(topic, fileId)}/map`, documentMapResponseSchema, {
        method: 'POST',
        signal: requestController.signal,
      });
      if (!requestController.signal.aborted && requestRevision === revision.current && currentTopic.current === topic) {
        responseRef.current = response;
        setState({ topic, fileId, response, loading: false, error: '' });
      }
    } catch (error) {
      if (!aborted(error) && requestRevision === revision.current && currentTopic.current === topic) {
        setState({ topic, fileId, response: responseRef.current, loading: false, error: errorText(error) });
      }
    } finally {
      activityApi.end();
    }
  }, [activity, activityApi, enabled, fileId, selectedFile, topic]);

  useEffect(
    () => () => {
      revision.current += 1;
      controller.current?.abort();
    },
    [],
  );

  const visibleState = state.topic === topic && state.fileId === fileId ? state : emptyState;
  return {
    fileId,
    setFileId: (id: string) => setSelection({ topic, fileId: id }),
    state: visibleState,
    build,
    reload: () => void load(true),
  };
}
