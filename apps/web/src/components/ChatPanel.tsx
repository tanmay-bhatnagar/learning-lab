import type { LabFile, Message, Model } from '../api/types';
import type { ContextMeter as Meter } from '../domain/contextMeter';
import { Composer } from './Composer';
import { GoalEditor } from './GoalEditor';
import { MessageList } from './MessageList';

type Props = {
  messages: Message[];
  models: Model[];
  topic: string;
  files: LabFile[];
  goalDraft: string;
  goalSavable: boolean;
  goalSaving: boolean;
  goalNotice: string;
  input: string;
  sending: boolean;
  busy: boolean;
  topicReady: boolean;
  follow: boolean;
  selectedCount: number;
  activeModel?: Model;
  modelError: string;
  meter: Meter;
  bottomRef: React.RefObject<HTMLDivElement | null>;
  thinkValue: (model?: Model) => boolean | string | undefined;
  onGoalChange: (value: string) => void;
  onGoalSubmit: (event: React.FormEvent) => void;
  onInputChange: (value: string) => void;
  onSend: (event: React.FormEvent) => void;
  onStop: () => void;
  onScroll: (event: React.UIEvent<HTMLDivElement>) => void;
  onFollowLatest: () => void;
  onOpenFiles: () => void;
  onOpenSettings: () => void;
  onThinkChange: (value: boolean | string, modelId?: string) => void;
  onRetryConnection: () => void;
  onStarterPrompt: (text: string) => void;
};

export function ChatPanel({
  messages,
  models,
  topic,
  files,
  goalDraft,
  goalSavable,
  goalSaving,
  goalNotice,
  input,
  sending,
  busy,
  topicReady,
  follow,
  selectedCount,
  activeModel,
  modelError,
  meter,
  bottomRef,
  thinkValue,
  onGoalChange,
  onGoalSubmit,
  onInputChange,
  onSend,
  onStop,
  onScroll,
  onFollowLatest,
  onOpenFiles,
  onOpenSettings,
  onThinkChange,
  onRetryConnection,
  onStarterPrompt,
}: Props) {
  return (
    <>
      <GoalEditor
        goalDraft={goalDraft}
        goalSavable={goalSavable}
        goalSaving={goalSaving}
        goalNotice={goalNotice}
        busy={busy}
        topicReady={topicReady}
        onChange={onGoalChange}
        onSubmit={onGoalSubmit}
      />
      <div className="conversation" onScroll={onScroll}>
        <MessageList
          messages={messages}
          models={models}
          topic={topic}
          files={files}
          sending={sending}
          bottomRef={bottomRef}
          onStarterPrompt={onStarterPrompt}
        />
      </div>
      <Composer
        input={input}
        sending={sending}
        busy={busy}
        topicReady={topicReady}
        follow={follow}
        hasMessages={messages.length > 0}
        selectedCount={selectedCount}
        activeModel={activeModel}
        modelError={modelError}
        meter={meter}
        bottomRef={bottomRef}
        thinkValue={thinkValue}
        onInputChange={onInputChange}
        onSend={onSend}
        onStop={onStop}
        onFollowLatest={onFollowLatest}
        onOpenFiles={onOpenFiles}
        onOpenSettings={onOpenSettings}
        onThinkChange={onThinkChange}
        onRetryConnection={onRetryConnection}
      />
    </>
  );
}
