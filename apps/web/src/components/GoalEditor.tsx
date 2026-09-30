import { MAX_LEARNING_GOAL_CHARS } from '../learningGoal';

type Props = {
  goalDraft: string;
  goalSavable: boolean;
  goalSaving: boolean;
  goalNotice: string;
  busy: boolean;
  topicReady: boolean;
  onChange: (value: string) => void;
  onSubmit: (event: React.FormEvent) => void;
};

export function GoalEditor({
  goalDraft,
  goalSavable,
  goalSaving,
  goalNotice,
  busy,
  topicReady,
  onChange,
  onSubmit,
}: Props) {
  return (
    <form className="goal-editor" onSubmit={onSubmit}>
      <label className="field">
        Your learning goal for this topic
        <textarea
          maxLength={MAX_LEARNING_GOAL_CHARS}
          rows={2}
          value={goalDraft}
          disabled={busy || !topicReady}
          onChange={(event) => onChange(event.target.value)}
          placeholder="What would you like to learn or be able to do?"
        />
        <span className="field-hint">
          This user-authored context is included in chat for this topic. {goalDraft.length}/{MAX_LEARNING_GOAL_CHARS}
        </span>
      </label>
      <button type="submit" className="secondary" disabled={!goalSavable}>
        {goalSaving ? 'Saving…' : 'Save learning goal'}
      </button>
      {goalNotice && (
        <span className="success" role="status">
          {goalNotice}
        </span>
      )}
    </form>
  );
}
