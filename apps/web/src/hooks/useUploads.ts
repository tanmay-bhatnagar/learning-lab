import { useCallback, useRef, useState, type RefObject } from 'react';
import { api, topicFilesPath } from '../api';
import type { LabFile } from '../api/types';
import { errorText } from '../lib/errors';
import { validatePdfs } from '../uploads';

export function useUploads(topic: string, topicRef: RefObject<string>) {
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [dropBlocked, setDropBlocked] = useState(false);
  const [dropFeedback, setDropFeedback] = useState('');
  const uploadLock = useRef(false);
  const dragDepth = useRef(0);
  const dropFeedbackTimer = useRef<number | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);

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
      blocked: string | null,
      setError: (message: string) => void,
      appendFile: (file: LabFile) => void,
    ) => {
      if (!list?.length || !topic) return;
      if (blocked) {
        setDropBlocked(true);
        showDropFeedback(blocked);
        return;
      }
      uploadLock.current = true;
      const target = topic;
      const batch = Array.from(list);
      setUploading(true);
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
          const result = await api<LabFile>(topicFilesPath(target), { method: 'POST', body });
          if (topicRef.current === target) appendFile(result);
        }
      } catch (e) {
        const message = errorText(e);
        setError(message);
        showDropFeedback(message);
        setDropBlocked(true);
      } finally {
        uploadLock.current = false;
        setUploading(false);
        if (uploadInput.current) uploadInput.current.value = '';
      }
    },
    [topic, topicRef, showDropFeedback],
  );

  const dispose = useCallback(() => {
    if (dropFeedbackTimer.current !== null) window.clearTimeout(dropFeedbackTimer.current);
  }, []);

  return {
    uploading,
    dragging,
    setDragging,
    dropBlocked,
    setDropBlocked,
    dropFeedback,
    dragDepthRef: dragDepth,
    uploadInput,
    uploadLock,
    upload,
    showDropFeedback,
    dispose,
  };
}
