import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  readPrerequisites,
  streamPrerequisites,
  type PrerequisiteAssessment,
  type PrerequisiteAttempt,
  type PrerequisiteGenerationInput,
  type PrerequisiteState,
} from '../api/prerequisites';
import { aborted, errorText } from '../lib/errors';
import type { Activity } from '../state/activity';
import type { useActivity } from './useActivity';

type ActivityApi = Pick<ReturnType<typeof useActivity>, 'begin' | 'end'>;

type Options = {
  topicId: string;
  fileId: string;
  sectionId: string;
  mapRevision: string;
  mapReady: boolean;
  activeCvId: string | null;
  activeCvHash: string | null;
  modelId?: string;
  contextLimit: number;
  think: PrerequisiteGenerationInput['think'];
  defaultGoal: string;
  activity: Activity;
  activityApi: ActivityApi;
  refreshProficiency: () => Promise<void>;
};

type ScopedState = { scope: string; value: PrerequisiteState };
type ScopedError = { scope: string; message: string };
type ScopedProgress = { scope: string; message: string };
type Generation = { scope: string; controller: AbortController; task: Promise<void> };

const identity = (options: Options): string =>
  [
    options.topicId,
    options.fileId,
    options.mapRevision,
    options.sectionId,
    options.activeCvId ?? '',
    options.activeCvHash ?? '',
  ].join(':');

function matchingAssessment(state: PrerequisiteState | null, options: Options): PrerequisiteAssessment | null {
  const assessment = state?.current_assessment;
  if (!assessment) return null;
  return assessment.topic_id === options.topicId &&
    assessment.file_id === options.fileId &&
    assessment.map_revision === options.mapRevision &&
    assessment.section_id === options.sectionId &&
    assessment.cv_id === options.activeCvId &&
    assessment.cv_text_sha256 === options.activeCvHash
    ? assessment
    : null;
}

function historicalAssessment(state: PrerequisiteState | null, options: Options): PrerequisiteAssessment | null {
  if (!state) return null;
  return (
    [...state.assessments]
      .filter(
        (assessment) =>
          assessment.topic_id === options.topicId &&
          assessment.file_id === options.fileId &&
          assessment.section_id === options.sectionId,
      )
      .sort((left, right) => right.finished_at.localeCompare(left.finished_at))[0] ?? null
  );
}

function latestAttempt(state: PrerequisiteState | null, options: Options): PrerequisiteAttempt | null {
  if (!state) return null;
  return (
    [...state.attempts]
      .filter(
        (attempt) =>
          attempt.topic_id === options.topicId &&
          attempt.file_id === options.fileId &&
          attempt.map_revision === options.mapRevision &&
          attempt.section_id === options.sectionId,
      )
      .sort((left, right) => right.started_at.localeCompare(left.started_at))[0] ?? null
  );
}

export function usePrerequisites(options: Options) {
  const scope = identity(options);
  const [savedState, setSavedState] = useState<ScopedState | null>(null);
  const [errorState, setErrorState] = useState<ScopedError | null>(null);
  const [progressState, setProgressState] = useState<ScopedProgress | null>(null);
  const [runningScope, setRunningScope] = useState('');
  const [reloadVersion, setReloadVersion] = useState(0);
  const generation = useRef<Generation | null>(null);
  const readController = useRef<AbortController | null>(null);
  const scopeRef = useRef(scope);
  const mounted = useRef(true);

  useLayoutEffect(() => {
    scopeRef.current = scope;
  }, [scope]);

  useEffect(() => {
    if (!options.topicId || !options.fileId || !options.sectionId || !options.mapRevision) return;
    const prior = generation.current;
    if (prior && prior.scope !== scope) prior.controller.abort();
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    let active = true;
    void readPrerequisites(options.topicId, options.fileId, options.sectionId, controller.signal)
      .then((value) => {
        if (active && !controller.signal.aborted && scopeRef.current === scope) {
          setSavedState({ scope, value });
          setErrorState((current) => (current?.scope === scope ? null : current));
        }
      })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted && scopeRef.current === scope) {
          setErrorState({ scope, message: errorText(error) });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [options.fileId, options.sectionId, options.topicId, options.mapRevision, reloadVersion, scope]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current?.controller.abort();
      readController.current?.abort();
    };
  }, []);

  const value = savedState?.scope === scope ? savedState.value : null;
  const error = errorState?.scope === scope ? errorState.message : '';
  const progress = progressState?.scope === scope ? progressState.message : '';
  const currentAssessment = matchingAssessment(value, options);
  const assessment = currentAssessment ?? historicalAssessment(value, options);
  const assessmentStaleReason =
    assessment && !currentAssessment
      ? assessment.map_revision !== options.mapRevision
        ? 'This saved assessment uses an older document map.'
        : assessment.cv_id !== options.activeCvId || assessment.cv_text_sha256 !== options.activeCvHash
          ? 'This saved assessment uses a different CV than the one currently selected.'
          : 'This saved assessment is historical and is not the current assessment.'
      : '';
  const attempt = latestAttempt(value, options);
  const loaded = !!value;
  const loading = !!options.sectionId && !!options.mapRevision && !loaded && !error;
  const cvMatches =
    !!options.activeCvId &&
    !!options.activeCvHash &&
    value?.selected_cv?.id === options.activeCvId &&
    value.selected_cv.extracted_sha256 === options.activeCvHash;

  let blockedReason = '';
  if (!options.sectionId) blockedReason = 'Select a section to assess its prerequisites.';
  else if (error && !loaded) blockedReason = error;
  else if (loading) blockedReason = 'Loading saved prerequisite state…';
  else if (!options.mapReady) blockedReason = 'Rebuild the document map before generating prerequisites.';
  else if (value?.map_revision !== options.mapRevision)
    blockedReason = 'The document map changed. Reload this section state.';
  else if (!options.activeCvId || !options.activeCvHash) blockedReason = 'Select a ready CV in My proficiency first.';
  else if (value?.selected_cv && !cvMatches) blockedReason = 'The selected CV changed. Reload this section state.';
  else if (!cvMatches) blockedReason = 'This section state is not yet linked to the selected CV.';
  else if (!options.modelId) blockedReason = 'Select an installed model in Settings before generating.';

  const reload = useCallback(() => {
    setReloadVersion((version) => version + 1);
  }, []);

  const generate = useCallback(
    async (goal = options.defaultGoal) => {
      const current = savedState?.scope === scope ? savedState.value : null;
      if (!current || blockedReason || generation.current || options.activity !== 'idle') return;
      const modelId = options.modelId;
      if (
        !modelId ||
        !options.activeCvId ||
        !options.activeCvHash ||
        !options.activityApi.begin('generatePrerequisites')
      )
        return;

      const controller = new AbortController();
      const requestScope = scope;
      setRunningScope(requestScope);
      setErrorState((previous) => (previous?.scope === requestScope ? null : previous));
      setProgressState({ scope: requestScope, message: 'Generating prerequisite assessment…' });

      const task = (async () => {
        let terminalError = '';
        let completed = false;
        try {
          await streamPrerequisites(
            options.topicId,
            options.fileId,
            options.sectionId,
            {
              revision: options.mapRevision,
              model: modelId,
              context_limit: options.contextLimit,
              think: options.think ?? null,
              goal,
            },
            controller.signal,
            (event) => {
              if (scopeRef.current !== requestScope) return;
              if (event.type === 'progress') {
                setProgressState({ scope: requestScope, message: 'Generating prerequisite assessment…' });
              } else if (event.type === 'done') {
                completed = true;
              } else if (event.type === 'error') {
                terminalError = event.message;
                setErrorState({ scope: requestScope, message: event.message });
              }
            },
          );
        } catch (reason) {
          if (!aborted(reason) && scopeRef.current === requestScope) {
            terminalError = errorText(reason);
            setErrorState({ scope: requestScope, message: terminalError });
          }
        } finally {
          if (generation.current?.scope === requestScope) generation.current = null;
          setRunningScope((currentScope) => (currentScope === requestScope ? '' : currentScope));
          if (mounted.current && scopeRef.current === requestScope) {
            setProgressState(null);
            try {
              const hydrateController = new AbortController();
              readController.current?.abort();
              readController.current = hydrateController;
              const latest = await readPrerequisites(
                options.topicId,
                options.fileId,
                options.sectionId,
                hydrateController.signal,
              );
              if (!hydrateController.signal.aborted && scopeRef.current === requestScope) {
                setSavedState({ scope: requestScope, value: latest });
                if (!terminalError) setErrorState((previous) => (previous?.scope === requestScope ? null : previous));
                if (completed) {
                  try {
                    await options.refreshProficiency();
                  } catch (reason) {
                    if (scopeRef.current === requestScope) {
                      setErrorState({
                        scope: requestScope,
                        message: `The assessment was saved, but My proficiency could not refresh: ${errorText(reason)}`,
                      });
                    }
                  }
                }
              }
            } catch (reason) {
              if (scopeRef.current === requestScope && !aborted(reason)) {
                setErrorState({ scope: requestScope, message: errorText(reason) });
              }
            }
          }
          options.activityApi.end();
        }
      })();
      generation.current = { scope: requestScope, controller, task };
      await task;
    },
    [blockedReason, options, savedState, scope],
  );

  const stop = useCallback(async () => {
    const current = generation.current;
    if (!current || current.scope !== scope) return;
    current.controller.abort();
    await current.task;
  }, [scope]);

  const running = runningScope === scope && options.activity === 'generatingPrerequisites';

  return {
    state: value,
    assessment,
    assessmentStaleReason,
    attempt,
    loading,
    running,
    progress,
    error,
    blockedReason,
    reload,
    generate,
    stop,
  };
}
