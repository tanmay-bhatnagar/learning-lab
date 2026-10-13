import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { PrerequisitePanel } from '../src/components/PrerequisitePanel';

const baseProps = {
  topicId: 'topic-a',
  fileId: 'file-a',
  sectionId: 'section-a',
  sectionTitle: 'First section',
  units: [],
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
});
