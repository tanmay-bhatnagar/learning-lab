import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { LearnerContext } from '../api/learnerContext';
import { importPrerequisites, type PrerequisiteAssessment } from '../api/prerequisites';
import { aborted, errorText } from '../lib/errors';
import type { Activity } from '../state/activity';
import type { useActivity } from './useActivity';

type ActivityApi = Pick<ReturnType<typeof useActivity>, 'begin' | 'end'>;

type Options = {
  topicId: string;
  conversationId: string;
  conversationTitle: string;
  assessment: PrerequisiteAssessment | null;
  assessmentStaleReason: string;
  sectionTitle: string;
  preference: LearnerContext | null;
  preferenceLoading: boolean;
  preferenceError: string;
  activity: Activity;
  activityApi: ActivityApi;
  onImported: () => void;
};

type ViewState = { scope: string; notice: string; error: string };
type PendingImport = { scope: string; controller: AbortController };

function scopeFor(options: Options): string {
  const assessment = options.assessment;
  return assessment
    ? [
        options.topicId,
        options.conversationId,
        options.conversationTitle,
        assessment.file_id,
        assessment.assessment_id,
        assessment.map_revision,
        assessment.section_id,
      ].join(':')
    : '';
}

function responseMatches(
  result: Awaited<ReturnType<typeof importPrerequisites>>,
  options: Options,
  preference: LearnerContext,
): boolean {
  const assessment = options.assessment;
  if (!assessment || result.conversation_id !== options.conversationId) return false;
  const metadata = result.message.prerequisite_import;
  const focus = result.learner_context.active_assessment;
  return (
    result.message.role === 'user' &&
    metadata.topic_id === options.topicId &&
    metadata.conversation_id === options.conversationId &&
    metadata.file_id === assessment.file_id &&
    metadata.assessment_id === assessment.assessment_id &&
    metadata.map_revision === assessment.map_revision &&
    metadata.section_id === assessment.section_id &&
    focus?.file_id === assessment.file_id &&
    focus.assessment_id === assessment.assessment_id &&
    focus.map_revision === assessment.map_revision &&
    focus.section_id === assessment.section_id &&
    focus.goal === metadata.goal &&
    result.learner_context.include_cv === preference.include_cv &&
    (result.learner_context.revision === preference.revision ||
      result.learner_context.revision === preference.revision + 1)
  );
}

export function usePrerequisiteImport(options: Options) {
  const scope = scopeFor(options);
  const [state, setState] = useState<ViewState | null>(null);
  const [pendingScope, setPendingScope] = useState('');
  const pending = useRef<PendingImport | null>(null);
  const mounted = useRef(true);
  const current = useRef({ scope, options });
  useLayoutEffect(() => {
    current.current = { scope, options };
  }, [options, scope]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      pending.current?.controller.abort();
    };
  }, []);

  useEffect(() => {
    const request = pending.current;
    if (request && request.scope !== scope) request.controller.abort();
    return () => {
      if (pending.current?.scope === scope) pending.current.controller.abort();
    };
  }, [scope]);

  const addToMainChat = useCallback(async () => {
    const captured = current.current;
    const selected = captured.options;
    const assessment = selected.assessment;
    const preference = selected.preference;
    if (!assessment || !selected.topicId || !selected.conversationId || !selected.conversationTitle) return;
    if (!preference || selected.preferenceLoading || selected.preferenceError) {
      setState({
        scope: captured.scope,
        notice: '',
        error: 'Reload My proficiency to verify the current conversation preference before adding this assessment.',
      });
      return;
    }
    if (selected.activity !== 'idle' || pending.current || !selected.activityApi.begin('importPrerequisites')) return;

    const controller = new AbortController();
    pending.current = { scope: captured.scope, controller };
    setPendingScope(captured.scope);
    setState({ scope: captured.scope, notice: '', error: '' });
    try {
      const result = await importPrerequisites(
        selected.topicId,
        selected.conversationId,
        {
          file_id: assessment.file_id,
          assessment_id: assessment.assessment_id,
          revision: assessment.map_revision,
          section_id: assessment.section_id,
          expected_revision: preference.revision,
        },
        controller.signal,
      );
      if (controller.signal.aborted || current.current.scope !== captured.scope) return;
      if (!responseMatches(result, selected, preference)) {
        setState({
          scope: captured.scope,
          notice: '',
          error: 'The server returned a different assessment or conversation. Reload before retrying.',
        });
        return;
      }
      setState({
        scope: captured.scope,
        notice: result.imported
          ? `Added to “${selected.conversationTitle}”.`
          : `Already in “${selected.conversationTitle}”.`,
        error: '',
      });
      selected.onImported();
    } catch (cause) {
      if (controller.signal.aborted || current.current.scope !== captured.scope || aborted(cause)) return;
      const message = errorText(cause);
      const conflict = /changed|conflict|revision|reload/i.test(message);
      setState({
        scope: captured.scope,
        notice: '',
        error: conflict ? `${message} Reload My proficiency and try again.` : message,
      });
    } finally {
      if (pending.current?.controller === controller) {
        pending.current = null;
        if (mounted.current) {
          setPendingScope((currentScope) => (currentScope === captured.scope ? '' : currentScope));
        }
      }
      selected.activityApi.end();
    }
  }, []);

  const visible = state?.scope === scope ? state : null;
  return {
    addToMainChat,
    importing: !!scope && pendingScope === scope,
    notice: visible?.notice ?? '',
    error: visible?.error ?? '',
  };
}
