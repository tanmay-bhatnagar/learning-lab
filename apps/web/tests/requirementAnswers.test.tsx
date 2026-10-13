import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';
import type { PrerequisiteAssessment } from '../src/api/prerequisites';
import type { ProficiencyEntryView } from '../src/domain/proficiency';
import { RequirementAnswers } from '../src/components/RequirementAnswers';

const assessment: PrerequisiteAssessment = {
  attempt_id: 'attempt-a',
  assessment_id: 'assessment-current',
  topic_id: 'topic-a',
  file_id: 'file-a',
  map_revision: 'a'.repeat(64),
  section_id: 'section-a',
  cv_id: 'c'.repeat(32),
  cv_text_sha256: 'b'.repeat(64),
  source_sha256: 'd'.repeat(64),
  overview: 'Review the main concepts.',
  requirements: [
    {
      requirement_id: 'req-python',
      concept: 'Python',
      reason: 'The section uses short programs in its examples.',
      question: 'Are you already comfortable with Python?',
      source_labels: ['S1'],
      cv_background: 'not_stated',
      cv_source_labels: [],
      cv_quote: '',
      comfort: null,
      comfort_status: 'pending',
    },
  ],
  sources: [{ label: 'S1', unit_id: 'unit-a', source_refs: ['doc:section-a'], pages: [1] }],
  finished_at: '2026-10-13T10:01:00Z',
};

const currentEntry: ProficiencyEntryView = {
  id: 'row-current',
  concept: 'Python',
  comfort: '',
  note: '',
  kind: 'requirement',
  requirementId: 'req-python',
  topicId: 'topic-a',
  assessmentId: 'assessment-current',
};
const oldEntry: ProficiencyEntryView = {
  ...currentEntry,
  id: 'row-old',
  comfort: 'new',
  note: 'Old self-report.',
  assessmentId: 'assessment-old',
};
const manualEntry: ProficiencyEntryView = {
  id: 'row-manual',
  concept: 'Python',
  comfort: 'refresher',
  note: 'Manual self-report.',
  kind: 'manual',
};
const baseProps = {
  assessment,
  sectionTitle: 'Synthetic section',
  fileName: 'paper-a.pdf',
  entries: [currentEntry, oldEntry, manualEntry],
  busy: false,
  saving: false,
  profileError: '',
  onSave: vi.fn(async () => undefined),
  onReload: vi.fn(),
};

describe('RequirementAnswers', () => {
  test('asks an explicit independent question and saves only the exact matching row after clicking Save', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn(async () => undefined);
    render(<RequirementAnswers {...baseProps} onSave={onSave} />);
    const card = screen.getByRole('article');

    expect(within(card).getByText('Are you already comfortable with Python?')).toBeInTheDocument();
    expect(within(card).getByLabelText('Your comfort with Python')).toHaveValue('');
    await user.selectOptions(within(card).getByLabelText('Your comfort with Python'), 'unsure');
    await user.type(within(card).getByLabelText('Notes for Python'), 'I have not used it yet.');

    expect(onSave).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Save proficiency' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave).toHaveBeenCalledWith([
      expect.objectContaining({
        id: 'row-current',
        concept: 'Python',
        comfort: 'unsure',
        note: 'I have not used it yet.',
        kind: 'requirement',
        requirementId: 'req-python',
        topicId: 'topic-a',
        assessmentId: 'assessment-current',
      }),
    ]);
  });

  test('keeps answer edits when the atomic save rejects', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn(async () => {
      throw new Error('My proficiency changed; reload it before saving this update.');
    });
    render(<RequirementAnswers {...baseProps} onSave={onSave} />);
    await user.selectOptions(screen.getByLabelText('Your comfort with Python'), 'new');
    await user.type(screen.getByLabelText('Notes for Python'), 'Pending note');
    await user.click(screen.getByRole('button', { name: 'Save proficiency' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/changed; reload/i);
    expect(screen.getByLabelText('Your comfort with Python')).toHaveValue('new');
    expect(screen.getByLabelText('Notes for Python')).toHaveValue('Pending note');
  });

  test('shows pending controls but disables save when a completed assessment has no exact saved row', () => {
    const onSave = vi.fn();
    render(<RequirementAnswers {...baseProps} entries={[]} onSave={onSave} />);

    expect(screen.getByLabelText('Your comfort with Python')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save proficiency' })).toBeDisabled();
    expect(screen.getByText(/no matching saved proficiency row/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload proficiency' })).toBeInTheDocument();
  });

  test('disables editing and saving when the global profile refresh failed', () => {
    render(<RequirementAnswers {...baseProps} profileError="Could not refresh My proficiency." />);

    expect(screen.getByLabelText('Your comfort with Python')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save proficiency' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reload proficiency' })).toBeInTheDocument();
  });

  test('refuses duplicate exact saved rows instead of choosing an ambiguous row', () => {
    render(<RequirementAnswers {...baseProps} entries={[currentEntry, { ...currentEntry, id: 'duplicate-row' }]} />);

    expect(screen.getByLabelText('Your comfort with Python')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save proficiency' })).toBeDisabled();
    expect(screen.getByText(/more than one saved proficiency row/i)).toBeInTheDocument();
  });

  test('refuses a saved row whose exact provenance matches but concept differs', () => {
    render(<RequirementAnswers {...baseProps} entries={[{ ...currentEntry, concept: 'Unrelated concept' }]} />);

    expect(screen.getByLabelText('Your comfort with Python')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save proficiency' })).toBeDisabled();
    expect(screen.getByText(/no matching saved proficiency row/i)).toBeInTheDocument();
  });
});
