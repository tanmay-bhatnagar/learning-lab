import { useCallback, useEffect, useRef, useState } from 'react';
import { api, json } from '../api/client';
import {
  streamDocumentSummary,
  summaryImportResponseSchema,
  type DocumentMap,
  type MapSection,
} from '../api/documentMap';
import { conversationSummaryImportsPath, fileSectionSummaryPath } from '../api/urls';
import type { Model } from '../api/types';
import { aborted, errorText } from '../lib/errors';
import {
  findMapSection,
  foldSummaryEvent,
  sectionSummaryState,
  type SectionSummaryState,
  type SummaryIdentity,
} from '../state/documentMap';
import type { Activity } from '../state/activity';
import type { useActivity } from './useActivity';

type ActivityApi = Pick<ReturnType<typeof useActivity>, 'begin' | 'end'>;

type Props = {
  topic: string;
  fileId: string;
  map: DocumentMap | null;
  conversationId: string;
  conversationTitle: string;
  model?: Model;
  contextLimit: number;
  think: boolean | string | undefined;
  activity: Activity;
  activityApi: ActivityApi;
  reloadMap: () => void;
  onImported: (conversationId: string) => void;
};

type Generation = { controller: AbortController; scope: string; task: Promise<void> };
type Import = { controller: AbortController; scope: string };

export function useSectionSummary({
  topic,
  fileId,
  map,
  conversationId,
  conversationTitle,
  model,
  contextLimit,
  think,
  activity,
  activityApi,
  reloadMap,
  onImported,
}: Props) {
  const [selection, setSelection] = useState({ topic, fileId, sectionId: '' });
  const sectionId = selection.topic === topic && selection.fileId === fileId ? selection.sectionId : '';
  const section = map && sectionId ? findMapSection(map.sections, sectionId) : null;
  const [view, setView] = useState<SectionSummaryState | null>(null);
  const [activeScope, setActiveScope] = useState('');
  const [notice, setNotice] = useState('');
  const generation = useRef<Generation | null>(null);
  const importRequest = useRef<Import | null>(null);
  const reloadMapRef = useRef(reloadMap);
  const conversationRef = useRef(conversationId);
  const activeIdentity: SummaryIdentity = {
    topic,
    fileId,
    revision: map?.revision ?? '',
    sectionId,
  };
  const scopeKey = `${topic}:${fileId}:${activeIdentity.revision}:${sectionId}`;
  const boundaryKey = `${topic}:${fileId}:${activeIdentity.revision}`;
  const priorBoundary = useRef(boundaryKey);
  const identityRef = useRef(activeIdentity);
  identityRef.current = activeIdentity;
  conversationRef.current = conversationId;
  reloadMapRef.current = reloadMap;

  useEffect(() => {
    if (priorBoundary.current !== boundaryKey) {
      priorBoundary.current = boundaryKey;
      setNotice('');
    }
    const current = generation.current;
    if (current && !current.scope.startsWith(`${boundaryKey}:`)) current.controller.abort();
    const currentImport = importRequest.current;
    if (currentImport && currentImport.scope !== boundaryKey) currentImport.controller.abort();
    if (selection.topic !== topic || selection.fileId !== fileId) {
      setSelection({ topic, fileId, sectionId: '' });
      setView(null);
      setNotice('');
    }
  }, [boundaryKey, fileId, selection.fileId, selection.topic, topic]);

  useEffect(() => {
    if (!map || !sectionId || !section) {
      setView(null);
      return;
    }
    if (generation.current?.scope === scopeKey) return;
    setView(sectionSummaryState({ topic, fileId, revision: map.revision, sectionId }, section));
  }, [
    fileId,
    map,
    scopeKey,
    section,
    section?.id,
    section?.last_summary?.id,
    section?.latest_attempt?.id,
    sectionId,
    topic,
  ]);

  useEffect(() => {
    if (!map || !sectionId) return;
    document.getElementById('selected-section-summary')?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, [fileId, sectionId, topic]);

  useEffect(
    () => () => {
      generation.current?.controller.abort();
      importRequest.current?.controller.abort();
    },
    [],
  );

  const selectSection = useCallback(
    (id: string) => {
      setSelection({ topic, fileId, sectionId: id });
      setNotice('');
    },
    [fileId, topic],
  );

  const generate = useCallback(async () => {
    if (!topic || !fileId || !map || map.revision !== activeIdentity.revision || !section || !model) return;
    if (generation.current || activity !== 'idle' || !activityApi.begin('generateSummary')) return;
    const requestController = new AbortController();
    const requestScope = scopeKey;
    const requestIdentity = { topic, fileId, revision: map.revision, sectionId: section.id };
    setActiveScope(requestScope);
    setNotice('');
    setView((previous) =>
      previous?.topic === topic && previous.fileId === fileId && previous.sectionId === section.id
        ? { ...previous, error: '' }
        : sectionSummaryState(requestIdentity, section),
    );
    const task = (async () => {
      try {
        await streamDocumentSummary(
          fileSectionSummaryPath(topic, fileId, section.id),
          { revision: map.revision, model: model.id, context_limit: contextLimit, think: think ?? null },
          requestController.signal,
          (event) => {
            const currentIdentity = identityRef.current;
            setView((previous) => (previous ? foldSummaryEvent(previous, event, currentIdentity) : previous));
            if (
              event.type === 'error' &&
              currentIdentity.topic === requestIdentity.topic &&
              currentIdentity.fileId === requestIdentity.fileId &&
              currentIdentity.revision === requestIdentity.revision &&
              currentIdentity.sectionId === requestIdentity.sectionId
            ) {
              setNotice(event.message);
            }
          },
        );
      } catch (error) {
        if (!aborted(error)) {
          setView((previous) =>
            previous?.topic === requestIdentity.topic &&
            previous.fileId === requestIdentity.fileId &&
            previous.revision === requestIdentity.revision &&
            previous.sectionId === requestIdentity.sectionId
              ? { ...previous, error: errorText(error) }
              : previous,
          );
          const currentIdentity = identityRef.current;
          if (
            currentIdentity.topic === requestIdentity.topic &&
            currentIdentity.fileId === requestIdentity.fileId &&
            currentIdentity.revision === requestIdentity.revision &&
            currentIdentity.sectionId === requestIdentity.sectionId
          ) {
            setNotice(errorText(error));
          }
        }
      } finally {
        if (generation.current?.scope === requestScope) generation.current = null;
        setActiveScope((previous) => (previous === requestScope ? '' : previous));
        activityApi.end();
        const currentIdentity = identityRef.current;
        if (
          currentIdentity.topic === requestIdentity.topic &&
          currentIdentity.fileId === requestIdentity.fileId &&
          currentIdentity.revision === requestIdentity.revision
        ) {
          reloadMapRef.current();
        }
      }
    })();
    generation.current = { controller: requestController, scope: requestScope, task };
    await task;
  }, [
    activity,
    activityApi,
    activeIdentity.revision,
    contextLimit,
    fileId,
    map,
    model,
    scopeKey,
    section,
    think,
    topic,
  ]);

  const stop = useCallback(async () => {
    const current = generation.current;
    if (!current) return;
    current.controller.abort();
    await current.task;
    if (identityRef.current.topic === topic && identityRef.current.fileId === fileId) reloadMapRef.current();
  }, [fileId, topic]);

  const addToConversation = useCallback(async () => {
    const saved = view?.summary;
    const identity = identityRef.current;
    const destination = conversationId;
    if (!saved || !destination || activity !== 'idle' || importRequest.current || !activityApi.begin('importSummary'))
      return;
    const controller = new AbortController();
    const requestScope = `${identity.topic}:${identity.fileId}:${identity.revision}`;
    importRequest.current = { controller, scope: requestScope };
    setNotice('');
    try {
      const result = await api(
        conversationSummaryImportsPath(identity.topic, destination),
        summaryImportResponseSchema,
        {
          ...json({
            file_id: identity.fileId,
            revision: saved.revision,
            section_id: saved.section_id,
            summary_id: saved.id,
          }),
          signal: controller.signal,
        },
      );
      const currentIdentity = identityRef.current;
      if (
        !controller.signal.aborted &&
        conversationRef.current === destination &&
        currentIdentity.topic === identity.topic &&
        currentIdentity.fileId === identity.fileId &&
        currentIdentity.revision === identity.revision
      ) {
        setNotice(result.imported ? `Added to “${conversationTitle}”.` : `Already in “${conversationTitle}”.`);
        onImported(destination);
      }
    } catch (error) {
      const currentIdentity = identityRef.current;
      if (
        !controller.signal.aborted &&
        conversationRef.current === destination &&
        currentIdentity.topic === identity.topic &&
        currentIdentity.fileId === identity.fileId &&
        currentIdentity.revision === identity.revision
      ) {
        setNotice(errorText(error));
      }
    } finally {
      if (importRequest.current?.controller === controller) importRequest.current = null;
      activityApi.end();
    }
  }, [activity, activityApi, conversationId, conversationTitle, onImported, view?.summary]);

  const currentView =
    view?.topic === topic && view.fileId === fileId && view.revision === map?.revision && view.sectionId === sectionId
      ? view
      : null;
  return {
    sectionId,
    section: section as MapSection | null,
    view: currentView,
    running: activeScope.startsWith(`${topic}:${fileId}:${activeIdentity.revision}:`),
    importing: activity === 'importingSummary',
    notice,
    selectSection,
    generate,
    stop,
    addToConversation,
  };
}
