import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import type { PrerequisiteAssessment } from '../src/api/prerequisites';
import { PrerequisitePanel } from '../src/components/PrerequisitePanel';

const assessment: PrerequisiteAssessment = {
  attempt_id: 'attempt-1',
  assessment_id: 'assessment-1',
  topic_id: 'topic-a',
  file_id: 'file-a',
  map_revision: 'a'.repeat(64),
  section_id: 'section-a',
  cv_id: 'c'.repeat(32),
  cv_text_sha256: 'b'.repeat(64),
  source_sha256: 'd'.repeat(64),
  overview: 'Review the core concepts before reading this section.',
  requirements: [
    {
      requirement_id: `req-${'e'.repeat(24)}`,
      concept: 'Basic Python',
      reason: 'The section uses short programs in its examples.',
      question: 'Are you already comfortable with Basic Python?',
      source_labels: ['S1'],
      cv_background: 'not_stated',
      cv_source_labels: [],
      cv_quote: '',
      comfort: null,
      comfort_status: 'pending',
    },
  ],
  sources: [{ label: 'S1', unit_id: 'unit-1', source_refs: ['doc:section-a'], pages: [2] }],
  finished_at: '2026-10-13T10:01:00Z',
};

const baseProps = {
  topicId: 'topic-a',
  fileId: 'file-a',
  fileName: 'paper-a.pdf',
  sectionId: 'section-a',
  sectionTitle: 'First section',
  units: [],
  proficiencyEntries: [],
  proficiencyError: '',
  proficiencySaving: false,
  assessment: null,
  assessmentStaleReason: '',
  attempt: null,
  loading: false,
  running: false,
  progress: '',
  error: '',
  blockedReason: '',
  modelName: 'local model',
  busy: false,
  defaultGoal: 'Understand this section',
  onGenerate: () => undefined,
  onStop: () => undefined,
  onReload: () => undefined,
  onOpenMyProficiency: () => undefined,
  onSaveProficiency: () => undefined,
  onReloadProficiency: () => undefined,
};

function SectionPanel({ sectionId }: { sectionId: string }) {
  return (
    <PrerequisitePanel
      key={`topic-a:file-a:map-revision:${sectionId}`}
      {...baseProps}
      sectionId={sectionId}
      sectionTitle={sectionId === 'section-a' ? 'First section' : 'Second section'}
    />
  );
}

describe('PrerequisitePanel section goal', () => {
  test('resets a customized goal when the selected section changes', () => {
    const view = render(<SectionPanel sectionId="section-a" />);
    const goal = screen.getByRole('textbox', { name: 'What do you want from this section?' });
    fireEvent.change(goal, { target: { value: 'Focus on the equations' } });

    view.rerender(<SectionPanel sectionId="section-b" />);

    expect(screen.getByRole('textbox', { name: 'What do you want from this section?' })).toHaveValue(
      'Understand this section',
    );
  });

  test('shows an independent pending answer editor and explicit save for each question', () => {
    render(<PrerequisitePanel {...baseProps} assessment={assessment} sectionTitle="First section" />);

    expect(screen.getByRole('combobox', { name: 'Your comfort with Basic Python' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Notes for Basic Python' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save proficiency' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reload proficiency' })).toBeInTheDocument();
  });

  test('does not claim CV experience was absent when there were no proposed concepts', () => {
    render(<PrerequisitePanel {...baseProps} assessment={{ ...assessment, requirements: [] }} />);

    expect(
      screen.getByText(/CV evidence was not assessed because this result identified no prerequisite concepts/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no relevant experience was stated in the CV/i)).not.toBeInTheDocument();
  });

  test('offers separate explicit main-chat import and editable follow-up actions', () => {
    const onAddToMainChat = vi.fn();
    const onDraftFollowUp = vi.fn();
    render(
      <PrerequisitePanel
        {...baseProps}
        assessment={assessment}
        mainChatTitle="Methods chat"
        canImportAssessment
        importing={false}
        importNotice=""
        importError=""
        onAddToMainChat={onAddToMainChat}
        onDraftFollowUp={onDraftFollowUp}
      />,
    );

    expect(screen.getByRole('button', { name: 'Add to “Methods chat”' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Draft a follow-up' })).toBeInTheDocument();
    expect(onAddToMainChat).not.toHaveBeenCalled();
    expect(onDraftFollowUp).not.toHaveBeenCalled();
  });
});
