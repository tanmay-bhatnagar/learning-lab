import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { fileMarkdownPath } from '../api/urls';
import { markdownResponseSchema, type LabFile } from '../api/types';
import { aborted, errorText } from '../lib/errors';

export function useFilePreview(topic: string, preview: LabFile | null, previewTab: 'markdown' | 'original') {
  const loadKey = `${topic}:${preview?.id ?? ''}:${previewTab}`;
  const [trackedKey, setTrackedKey] = useState(loadKey);
  const [markdown, setMarkdown] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');

  if (loadKey !== trackedKey) {
    setTrackedKey(loadKey);
    setMarkdown('');
    setPreviewError('');
    setPreviewLoading(Boolean(preview && previewTab === 'markdown' && topic));
  }

  useEffect(() => {
    if (!preview || previewTab !== 'markdown' || !topic) return;
    const controller = new AbortController();
    api(fileMarkdownPath(topic, preview.id), markdownResponseSchema, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setMarkdown(data.markdown);
      })
      .catch((e) => {
        if (!aborted(e)) setPreviewError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setPreviewLoading(false);
      });
    return () => controller.abort();
  }, [loadKey, preview, previewTab, topic]);

  return { markdown, previewLoading, previewError };
}
