import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { getLearnerContext, updateLearnerContext, type LearnerContext } from '../api/learnerContext';
import { errorText } from '../lib/errors';
import type { Activity } from '../state/activity';
import type { useActivity } from './useActivity';

type ActivityApi = Pick<ReturnType<typeof useActivity>, 'begin' | 'end'>;

type Options = {
  topicId: string | null;
  conversationId: string | null;
  activity: Activity;
  activityApi: ActivityApi;
};

type PreferenceState = {
  target: string;
  preference: LearnerContext;
};

type ErrorState = { target: string; message: string };

export function useLearnerContext({ topicId, conversationId, activity, activityApi }: Options) {
  const target = topicId && conversationId ? `${topicId}/${conversationId}` : '';
  const [state, setState] = useState<PreferenceState | null>(null);
  const [errorState, setErrorState] = useState<ErrorState | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const saveInFlight = useRef(false);
  const saveController = useRef<AbortController | null>(null);
  const targetRef = useRef(target);
  useLayoutEffect(() => {
    targetRef.current = target;
  }, [target]);

  useEffect(() => {
    saveController.current?.abort();
    saveController.current = null;
    saveInFlight.current = false;
    if (!target || !topicId || !conversationId) return;

    const controller = new AbortController();
    let active = true;
    void getLearnerContext(topicId, conversationId, controller.signal)
      .then((preference) => {
        if (active && !controller.signal.aborted && targetRef.current === target) setState({ target, preference });
      })
      .catch((reason: unknown) => {
        if (active && !controller.signal.aborted && targetRef.current === target) {
          setErrorState({ target, message: errorText(reason) });
        }
      });

    return () => {
      active = false;
      controller.abort();
      saveController.current?.abort();
    };
  }, [conversationId, reloadVersion, target, topicId]);

  const setIncludeCv = useCallback(
    async (includeCv: boolean) => {
      if (!topicId || !conversationId || !target) return;
      const current = state?.target === target ? state.preference : null;
      if (!current || saveInFlight.current) return;
      if (!activityApi.begin('saveLearnerContext')) return;

      const saveTarget = target;
      const controller = new AbortController();
      saveController.current = controller;
      saveInFlight.current = true;
      setErrorState(null);
      try {
        const updated = await updateLearnerContext(
          topicId,
          conversationId,
          { expected_revision: current.revision, include_cv: includeCv },
          controller.signal,
        );
        if (!controller.signal.aborted && targetRef.current === saveTarget) {
          setState({ target: saveTarget, preference: updated });
        }
      } catch (reason) {
        if (!controller.signal.aborted && targetRef.current === saveTarget) {
          setErrorState({ target: saveTarget, message: errorText(reason) });
        }
      } finally {
        if (saveController.current === controller) {
          saveController.current = null;
          saveInFlight.current = false;
        }
        activityApi.end();
      }
    },
    [activityApi, conversationId, state, target, topicId],
  );

  const preference = state?.target === target ? state.preference : null;
  const error = errorState?.target === target ? errorState.message : '';
  const loading = !!target && !preference && !error;
  const reload = useCallback(() => {
    setErrorState((current) => (current?.target === target ? null : current));
    setReloadVersion((version) => version + 1);
  }, [target]);

  return {
    preference,
    loading: !!target && (loading || !preference),
    error,
    reload,
    setIncludeCv,
    saving: activity === 'savingLearnerContext',
  };
}
