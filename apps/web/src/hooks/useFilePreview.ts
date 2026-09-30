import { useEffect, useState } from 'react';
import { api, fileMarkdownPath } from '../api';
import { markdownResponseSchema, type LabFile } from '../api/types';
import { aborted, errorText } from '../lib/errors';

export function useFilePreview(topic: string, preview: LabFile | null, previewTab: 'markdown' | 'original') {
  const [markdown, setMarkdown] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');

  useEffect(() => {
    if (!preview || previewTab !== 'markdown' || !topic) return;
    const controller = new AbortController();
    setPreviewLoading(true);
    setPreviewError('');
    setMarkdown('');
    api(fileMarkdownPath(topic, preview.id), markdownResponseSchema, { signal: controller.signal })
      .then((data) => setMarkdown(data.markdown))
      .catch((e) => {
        if (!aborted(e)) setPreviewError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setPreviewLoading(false);
      });
    return () => controller.abort();
  }, [preview, previewTab, topic]);

  return { markdown, previewLoading, previewError };
}
