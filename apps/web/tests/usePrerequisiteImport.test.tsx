import { act, renderHook } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import type { LearnerContext } from '../src/api/learnerContext';
import {
  importPrerequisites,
  type PrerequisiteAssessment,
  type PrerequisiteImportResponse,
} from '../src/api/prerequisites';
import type { Activity } from '../src/state/activity';
import { usePrerequisiteImport } from '../src/hooks/usePrerequisiteImport';

vi.mock('../src/api/prerequisites', () => ({ importPrerequisites: vi.fn() }));

const revision = 'a'.repeat(64);
const focus = {
  file_id: 'file-a',
  assessment_id: 'assessment-a',
  map_revision: revision,
  section_id: 'section-a',
  goal: 'Understand this section.',
};
const assessment: PrerequisiteAssessment = {
  attempt_id: 'attempt-a',
  assessment_id: focus.assessment_id,
  topic_id: 'topic-a',
  file_id: focus.file_id,
  map_revision: focus.map_revision,
  section_id: focus.section_id,
  cv_id: 'c'.repeat(32),
  cv_text_sha256: 'b'.repeat(64),
  source_sha256: 'd'.repeat(64),
  overview: 'Review the main concepts.',
  requirements: [],
  sources: [{ label: 'S1', unit_id: 'unit-a', source_refs: ['doc:section-a'], pages: [1] }],
  finished_at: '2026-10-13T10:01:00Z',
};
const preference: LearnerContext = {
  schema_version: 1,
  revision: 7,
  include_cv: true,
  active_assessment: null,
};
const metadata = {
  schema_version: 1 as const,
  import_id: 'e'.repeat(64),
  conversation_id: 'conversation-a',
  topic_id: 'topic-a',
  file_id: 'file-a',
  assessment_id: 'assessment-a',
  map_revision: revision,
  section_id: 'section-a',
  section_title: 'Results',
  goal: focus.goal,
  model: 'local-model',
  assessment_finished_at: assessment.finished_at,
  imported_at: '2026-10-13T10:02:00Z',
  sources: assessment.sources,
  content_sha256: 'f'.repeat(64),
};
const importedMessage = {
  role: 'user' as const,
  content: 'Saved prerequisite snapshot.',
  prerequisite_import: metadata,
};
const importResult: PrerequisiteImportResponse = {
  conversation_id: 'conversation-a',
  imported: true,
  message: importedMessage,
  messages: [importedMessage],
  learner_context: {
    schema_version: 1,
    revision: 8,
    include_cv: true,
    active_assessment: focus,
  },
  context: null,
};

function setup() {
  const begin = vi.fn(() => true);
  const end = vi.fn();
  const onImported = vi.fn();
  const options = {
    topicId: 'topic-a',
    conversationId: 'conversation-a',
    conversationTitle: 'Methods chat',
    assessment,
    assessmentStaleReason: '',
    sectionTitle: 'Results',
    preference,
    preferenceLoading: false,
    preferenceError: '',
    activity: 'idle' as Activity,
    activityApi: { begin, end },
    onImported,
  };
  return { options, begin, end, onImported };
}

describe('usePrerequisiteImport', () => {
  test('imports the captured assessment to the named conversation with its current preference revision', async () => {
    vi.mocked(importPrerequisites).mockResolvedValue(importResult);
    const { options, begin, end, onImported } = setup();
    const { result } = renderHook(() => usePrerequisiteImport(options));

    await act(async () => result.current.addToMainChat());

    expect(begin).toHaveBeenCalledWith('importPrerequisites');
    expect(importPrerequisites).toHaveBeenCalledWith(
      'topic-a',
      'conversation-a',
      {
        file_id: 'file-a',
        assessment_id: 'assessment-a',
        revision,
        section_id: 'section-a',
        expected_revision: 7,
      },
      expect.any(AbortSignal),
    );
    expect(onImported).toHaveBeenCalledTimes(1);
    expect(result.current.notice).toMatch(/Methods chat/);
    expect(end).toHaveBeenCalledTimes(1);
  });

  test('does not import a stale assessment or guess a missing preference revision', async () => {
    vi.mocked(importPrerequisites).mockClear();
    const stale = setup();
    const { result, rerender } = renderHook((props) => usePrerequisiteImport(props), {
      initialProps: stale.options,
    });
    rerender({ ...stale.options, assessmentStaleReason: 'The document map changed.' });

    await act(async () => result.current.addToMainChat());

    expect(importPrerequisites).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/reload|current/i);
  });

  test('requires a loaded typed preference before starting an import', async () => {
    vi.mocked(importPrerequisites).mockClear();
    const { options, begin, end } = setup();
    const { result } = renderHook(() =>
      usePrerequisiteImport({ ...options, preference: null, preferenceLoading: true }),
    );

    await act(async () => result.current.addToMainChat());

    expect(importPrerequisites).not.toHaveBeenCalled();
    expect(begin).not.toHaveBeenCalled();
    expect(end).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/reload My proficiency/i);
  });

  test('reports idempotent retries as already present while refreshing the conversation', async () => {
    vi.mocked(importPrerequisites).mockResolvedValue({ ...importResult, imported: false });
    const { options, onImported } = setup();
    const { result } = renderHook(() => usePrerequisiteImport(options));

    await act(async () => result.current.addToMainChat());

    expect(result.current.notice).toBe('Already in “Methods chat”.');
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  test('guards same-tick repeated clicks and validates the saved response identity', async () => {
    let resolveImport: ((value: PrerequisiteImportResponse) => void) | undefined;
    vi.mocked(importPrerequisites).mockImplementation(() => new Promise((resolve) => (resolveImport = resolve)));
    const { options, begin, onImported } = setup();
    const { result } = renderHook(() => usePrerequisiteImport(options));

    let first: Promise<void> | undefined;
    let second: Promise<void> | undefined;
    act(() => {
      first = result.current.addToMainChat();
      second = result.current.addToMainChat();
    });
    expect(result.current.importing).toBe(true);
    expect(begin).toHaveBeenCalledTimes(1);
    resolveImport?.({
      ...importResult,
      message: {
        ...importResult.message,
        prerequisite_import: { ...metadata, conversation_id: 'conversation-wrong' },
      },
    });
    await act(async () => {
      await Promise.all([first, second]);
    });

    expect(onImported).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/different assessment or conversation/i);
  });

  test('ignores a late response after switching to another destination', async () => {
    let resolveImport: ((value: PrerequisiteImportResponse) => void) | undefined;
    vi.mocked(importPrerequisites).mockImplementation(() => new Promise((resolve) => (resolveImport = resolve)));
    const { options, onImported } = setup();
    const { result, rerender } = renderHook((props) => usePrerequisiteImport(props), { initialProps: options });

    let pending: Promise<void> | undefined;
    act(() => {
      pending = result.current.addToMainChat();
    });
    rerender({ ...options, conversationId: 'conversation-b', conversationTitle: 'Other chat' });
    await act(async () => {
      resolveImport?.(importResult);
      await pending;
    });

    expect(onImported).not.toHaveBeenCalled();
    expect(result.current.notice).toBe('');
  });

  test('keeps failures actionable and ends the shared activity', async () => {
    vi.mocked(importPrerequisites).mockRejectedValue(new Error('Conversation preferences changed; reload first.'));
    const { options, end } = setup();
    const { result } = renderHook(() => usePrerequisiteImport(options));

    await act(async () => result.current.addToMainChat());

    expect(result.current.error).toMatch(/reload My proficiency and try again/i);
    expect(end).toHaveBeenCalledTimes(1);
  });

  test('ignores a late import completion after the hook unmounts', async () => {
    let resolveImport: ((value: PrerequisiteImportResponse) => void) | undefined;
    vi.mocked(importPrerequisites).mockImplementation(() => new Promise((resolve) => (resolveImport = resolve)));
    const { options, onImported } = setup();
    const { result, unmount } = renderHook(() => usePrerequisiteImport(options));

    let pending: Promise<void> | undefined;
    act(() => {
      pending = result.current.addToMainChat();
    });
    unmount();
    await act(async () => {
      resolveImport?.(importResult);
      await pending;
    });

    expect(onImported).not.toHaveBeenCalled();
  });
});
