import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';
import { MyProficiencyPanel } from '../src/components/MyProficiencyPanel';
import type { MyProficiencyPanelProps } from '../src/components/MyProficiencyPanel';

const baseProps: MyProficiencyPanelProps = {
  requirements: [],
  entries: [],
  cvs: [],
  selectedCvId: '',
  activeConversationId: '',
  includeCv: false,
  busy: false,
  saving: false,
  error: '',
  notice: '',
  onSave: vi.fn(),
  onUploadCv: vi.fn(async () => undefined),
  onSelectCv: vi.fn(),
  onRevokeCv: vi.fn(),
  onIncludeCvChange: vi.fn(),
};

function uploadInput() {
  return screen.getByLabelText('Upload your CV') as HTMLInputElement;
}

describe('My proficiency panel', () => {
  test('allows adding and explicitly saving a manual skill without a CV', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<MyProficiencyPanel {...baseProps} onSave={onSave} />);

    await user.type(screen.getByRole('textbox', { name: 'Add a skill or concept' }), 'Basic Python');
    await user.click(screen.getByRole('button', { name: 'Add skill' }));
    const skill = screen.getByRole('group', { name: 'Basic Python' });
    await user.selectOptions(within(skill).getByLabelText('Your comfort with Basic Python'), 'new');
    await user.type(within(skill).getByLabelText('Notes for Basic Python'), 'I have not used it yet.');

    expect(onSave).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Save proficiency' }));
    expect(onSave).toHaveBeenCalledWith([
      expect.objectContaining({ concept: 'Basic Python', comfort: 'new', note: 'I have not used it yet.' }),
    ]);
  });

  test('reconciles a saved manual draft with the server-assigned entry ID', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const view = render(<MyProficiencyPanel {...baseProps} onSave={onSave} />);
    await user.type(screen.getByRole('textbox', { name: 'Add a skill or concept' }), 'Basic Python');
    await user.click(screen.getByRole('button', { name: 'Add skill' }));
    const draft = screen.getByRole('group', { name: 'Basic Python' });
    await user.selectOptions(within(draft).getByLabelText('Your comfort with Basic Python'), 'new');
    await user.click(screen.getByRole('button', { name: 'Save proficiency' }));

    view.rerender(
      <MyProficiencyPanel
        {...baseProps}
        entries={[{ id: 'server-entry-1', concept: 'Basic Python', comfort: 'new', note: '', kind: 'manual' }]}
        onSave={onSave}
      />,
    );

    expect(screen.getAllByRole('group', { name: 'Basic Python' })).toHaveLength(1);
    expect(screen.getByLabelText('Your comfort with Basic Python')).toHaveValue('new');
  });

  test('asks independently about every model requirement and keeps its recommendation distinct from self-report', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const view = render(
      <MyProficiencyPanel
        {...baseProps}
        requirements={[
          { id: 'python', concept: 'Python', rationale: 'Needed to run the examples.', sourceLabel: 'CV and paper' },
          {
            id: 'statistics',
            concept: 'Statistics',
            rationale: 'Needed to interpret the results.',
            sourceLabel: 'Paper',
          },
        ]}
        onSave={onSave}
      />,
    );

    expect(screen.getAllByText('Model suggestion')).toHaveLength(2);
    expect(screen.getAllByText('User self-report')).toHaveLength(2);
    const python = screen.getByRole('group', { name: 'Python' });
    const statistics = screen.getByRole('group', { name: 'Statistics' });
    expect(within(python).getByText('Are you already comfortable with Python?')).toBeInTheDocument();
    expect(within(statistics).getByText('Are you already comfortable with Statistics?')).toBeInTheDocument();
    expect(within(python).getByLabelText('Your comfort with Python')).toHaveValue('');
    expect(within(statistics).getByLabelText('Your comfort with Statistics')).toHaveValue('');
    await user.selectOptions(within(python).getByLabelText('Your comfort with Python'), 'unsure');
    expect(within(statistics).getByLabelText('Your comfort with Statistics')).toHaveValue('');
    expect(onSave).not.toHaveBeenCalled();

    view.rerender(
      <MyProficiencyPanel
        {...baseProps}
        requirements={[
          { id: 'python', concept: 'Python', rationale: 'Updated evidence.', sourceLabel: 'Paper' },
          {
            id: 'statistics',
            concept: 'Statistics',
            rationale: 'Needed to interpret the results.',
            sourceLabel: 'Paper',
          },
          { id: 'algebra', concept: 'Algebra', rationale: 'Needed for the notation.', sourceLabel: 'Paper' },
        ]}
      />,
    );
    expect(screen.getByLabelText('Your comfort with Python')).toHaveValue('unsure');
    expect(screen.getByLabelText('Your comfort with Algebra')).toHaveValue('');
  });

  test('uses the exact edited CV filename and waits for explicit upload submission', async () => {
    const user = userEvent.setup();
    const onUploadCv = vi.fn(async () => undefined);
    render(<MyProficiencyPanel {...baseProps} onUploadCv={onUploadCv} />);
    const file = new File(['Synthetic CV'], 'resume.pdf', { type: 'application/pdf' });
    fireEvent.change(uploadInput(), { target: { files: [file] } });
    const filename = screen.getByRole('textbox', { name: 'CV filename' });
    await user.clear(filename);
    await user.type(filename, 'Research CV.pdf');

    expect(onUploadCv).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Upload CV' }));
    await waitFor(() => expect(onUploadCv).toHaveBeenCalledWith(file, 'Research CV.pdf'));
  });

  test('keeps manual answers visible and reports a proficiency save failure', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn(async () => {
      throw new Error('Could not save proficiency.');
    });
    render(<MyProficiencyPanel {...baseProps} onSave={onSave} />);
    await user.type(screen.getByRole('textbox', { name: 'Add a skill or concept' }), 'Linear algebra');
    await user.click(screen.getByRole('button', { name: 'Add skill' }));
    const skill = screen.getByRole('group', { name: 'Linear algebra' });
    await user.selectOptions(within(skill).getByLabelText('Your comfort with Linear algebra'), 'refresher');
    await user.click(screen.getByRole('button', { name: 'Save proficiency' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save proficiency.');
    expect(within(skill).getByLabelText('Your comfort with Linear algebra')).toHaveValue('refresher');
  });

  test('prevents a second proficiency save while the first save is pending', async () => {
    let finishSave: (() => void) | undefined;
    const onSave = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishSave = resolve;
        }),
    );
    render(<MyProficiencyPanel {...baseProps} onSave={onSave} />);
    const saveButton = screen.getByRole('button', { name: 'Save proficiency' });

    fireEvent.click(saveButton);
    fireEvent.click(saveButton);

    expect(onSave).toHaveBeenCalledTimes(1);
    finishSave?.();
  });

  test('keeps the selected file and editable name visible when duplicate-name upload fails', async () => {
    const user = userEvent.setup();
    const onUploadCv = vi.fn(async () => {
      throw new Error('A CV with this filename already exists. Rename it and try again.');
    });
    render(<MyProficiencyPanel {...baseProps} onUploadCv={onUploadCv} />);
    const file = new File(['Synthetic CV'], 'resume.pdf', { type: 'application/pdf' });
    fireEvent.change(uploadInput(), { target: { files: [file] } });
    await user.click(screen.getByRole('button', { name: 'Upload CV' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/already exists.*Rename it/i);
    expect(screen.getByRole('textbox', { name: 'CV filename' })).toHaveValue('resume.pdf');
    expect(uploadInput().files?.[0]).toBe(file);
  });

  test('shows a text-only extraction preview and scopes full-CV inclusion to the active conversation', async () => {
    const user = userEvent.setup();
    const onIncludeCvChange = vi.fn();
    render(
      <MyProficiencyPanel
        {...baseProps}
        cvs={[
          {
            id: 'cv-1',
            originalName: 'Research CV.pdf',
            status: 'ready',
            extractedText: 'Synthetic extracted CV text.',
            extractionDiagnostics: [],
          },
        ]}
        selectedCvId="cv-1"
        activeConversationId="conversation-1"
        onIncludeCvChange={onIncludeCvChange}
      />,
    );

    expect(screen.getByText('Synthetic extracted CV text.')).toBeInTheDocument();
    expect(
      screen.getByText('Complete extracted text is included on every applicable turn and uses more context.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Always include CV in this conversation' }));
    expect(onIncludeCvChange).toHaveBeenCalledWith(true);
  });

  test('allows disabling always-include after the selected CV becomes unavailable', async () => {
    const user = userEvent.setup();
    const onIncludeCvChange = vi.fn();
    render(
      <MyProficiencyPanel
        {...baseProps}
        cvs={[
          {
            id: 'cv-1',
            originalName: 'Revoked CV.pdf',
            status: 'revoked',
            extractedText: '',
            extractionDiagnostics: [],
          },
        ]}
        selectedCvId="cv-1"
        activeConversationId="conversation-1"
        includeCv
        onIncludeCvChange={onIncludeCvChange}
      />,
    );

    const toggle = screen.getByRole('checkbox', { name: 'Always include CV in this conversation' });
    expect(toggle).toBeChecked();
    expect(toggle).toBeEnabled();
    await user.click(toggle);
    expect(onIncludeCvChange).toHaveBeenCalledWith(false);
  });
});
