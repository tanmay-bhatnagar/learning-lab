import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { readSavedPrerequisites, type PrerequisiteAssessment } from '../api/prerequisites';
import type { LearnerContext } from '../api/learnerContext';
import { errorText } from '../lib/errors';

type SavedFocus = Pick<
  NonNullable<LearnerContext['active_assessment']>,
  'file_id' | 'assessment_id' | 'map_revision' | 'section_id'
>;
type LoadedAssessment = { target: string; assessment: PrerequisiteAssessment };
type FocusError = { target: string; message: string };

const focusTarget = (topicId: string, focus: SavedFocus | null): string =>
  focus ? [topicId, focus.file_id, focus.map_revision, focus.section_id, focus.assessment_id].join(':') : '';

export function useFocusedAssessment(
  topicId: string,
  focus: SavedFocus | null,
  fallback: PrerequisiteAssessment | null,
) {
  const target = focusTarget(topicId, focus);
  const [loaded, setLoaded] = useState<LoadedAssessment | null>(null);
  const [errorState, setErrorState] = useState<FocusError | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const targetRef = useRef(target);

  useLayoutEffect(() => {
    targetRef.current = target;
  }, [target]);

  useEffect(() => {
    if (!focus || !target) return;
    const controller = new AbortController();
    let active = true;
    void readSavedPrerequisites(topicId, focus.file_id, focus.assessment_id, controller.signal)
      .then((state) => {
        if (!active || controller.signal.aborted || targetRef.current !== target) return;
        const assessment = state.assessments.find(
          (item) =>
            item.topic_id === topicId &&
            item.file_id === focus.file_id &&
            item.assessment_id === focus.assessment_id &&
            item.map_revision === focus.map_revision &&
            item.section_id === focus.section_id,
        );
        if (!assessment) {
          setErrorState({ target, message: 'The assessment saved in this conversation is no longer available.' });
          setLoaded((current) => (current?.target === target ? null : current));
          return;
        }
        setLoaded({ target, assessment });
        setErrorState((current) => (current?.target === target ? null : current));
      })
      .catch((reason: unknown) => {
        if (active && !controller.signal.aborted && targetRef.current === target) {
          setErrorState({ target, message: errorText(reason) });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [focus, reloadVersion, target, topicId]);

  const reload = useCallback(() => {
    setErrorState((current) => (current?.target === target ? null : current));
    setReloadVersion((version) => version + 1);
  }, [target]);

  const assessment = focus ? (loaded?.target === target ? loaded.assessment : null) : fallback;
  const error = focus && errorState?.target === target ? errorState.message : '';
  const loading = !!focus && !assessment && !error;
  return { assessment, loading, error, reload };
}
