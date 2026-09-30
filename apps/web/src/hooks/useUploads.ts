import { useCallback, useRef, useState, type RefObject } from 'react';
import { api } from '../api/client';
import { topicFilesPath } from '../api/urls';
import { labFileSchema, type LabFile } from '../api/types';
import { errorText } from '../lib/errors';
import { uploadBlockedReason, type Activity } from '../state/activity';
import { validatePdfs } from '../uploads';
import type { useActivity } from './useActivity';

type ActivityApi = Pick<ReturnType<typeof useActivity>, 'begin' | 'end'>;

export function useUploads(
  topic: string,
  topicRef: RefObject<string>,
  activity: Activity,
  topicReady: boolean,
  activityApi: ActivityApi,
) {
  const [dragging, setDragging] = useState(false);
  const [dropBlocked, setDropBlocked] = useState(false);
  const [dropFeedback, setDropFeedback] = useState('');
  const dragDepth = useRef(0);
  const dropFeedbackTimer = useRef<number | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);

  const uploadBlocked = uploadBlockedReason(activity, { topicReady, hasTopic: !!topic });

  const showDropFeedback = useCallback((message: string) => {
    setDropFeedback(message);
    if (dropFeedbackTimer.current !== null) window.clearTimeout(dropFeedbackTimer.current);
    dropFeedbackTimer.current = window.setTimeout(() => {
      setDropFeedback('');
      dropFeedbackTimer.current = null;
    }, 6000);
  }, []);

  const upload = useCallback(
    async (
      list: FileList | File[] | null,
      parser: string,
      setError: (message: string) => void,
      appendFile: (file: LabFile) => void,
    ) => {
      if (!list?.length || !topic) return;
      if (uploadBlocked) {
        setDropBlocked(true);
        showDropFeedback(uploadBlocked);
        return;
      }
      if (!activityApi.begin('upload')) return;
      const target = topic;
      const batch = Array.from(list);
      setDragging(false);
      setDropBlocked(false);
      dragDepth.current = 0;
      setError('');
      setDropFeedback('');
      try {
        await validatePdfs(batch);
        for (const file of batch) {
          const body = new FormData();
          body.append('file', file);
          body.append('parser', parser);
          const result = await api(topicFilesPath(target), labFileSchema, { method: 'POST', body });
          if (topicRef.current === target) appendFile(result);
        }
      } catch (e) {
        if (topicRef.current !== target) return;
        const message = errorText(e);
        setError(message);
        showDropFeedback(message);
        setDropBlocked(true);
      } finally {
        activityApi.end();
        if (uploadInput.current) uploadInput.current.value = '';
      }
    },
    [topic, topicRef, uploadBlocked, showDropFeedback, activityApi],
  );

  const dispose = useCallback(() => {
    if (dropFeedbackTimer.current !== null) window.clearTimeout(dropFeedbackTimer.current);
  }, []);

  return {
    dragging,
    setDragging,
    dropBlocked,
    setDropBlocked,
    dropFeedback,
    dragDepthRef: dragDepth,
    uploadInput,
    uploadBlocked,
    upload,
    showDropFeedback,
    dispose,
  };
}
