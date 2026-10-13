import { createRef } from 'react';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { LabFile, Message } from '../src/api/types';
import { MessageList } from '../src/components/MessageList';

const sha = 'a'.repeat(64);

function prerequisiteMessage(overrides: Record<string, unknown> = {}): Message {
  return {
    role: 'user',
    content:
      'Saved prerequisites — Results\nSuggestions are model-inferred, not verified prerequisites or proof of mastery.\n\nAre you already comfortable with Python basics? — Not yet',
    prerequisite_import: {
      schema_version: 1,
      import_id: 'b'.repeat(64),
      conversation_id: 'conversation-a',
      topic_id: 'topic-a',
      file_id: 'paper-a',
      assessment_id: 'assessment-a',
      map_revision: sha,
      section_id: 'results',
      section_title: 'Results',
      goal: 'Understand the paper methods',
      model: 'qwen-local',
      assessment_finished_at: '2026-10-13T10:01:00Z',
      imported_at: '2026-10-13T10:02:00Z',
      sources: [
        { label: 'S1', unit_id: 'unit-a', source_refs: ['ref-a'], pages: [2, 4] },
        { label: 'S2', unit_id: 'unit-b', source_refs: ['ref-b'], pages: [11] },
      ],
      content_sha256: sha,
    },
    ...overrides,
  } as Message;
}

function renderMessages(messages: Message[], files: LabFile[] = []) {
  return render(
    <MessageList
      messages={messages}
      models={[]}
      topic="topic-a"
      files={files}
      sending={false}
      bottomRef={createRef<HTMLDivElement>()}
      onStarterPrompt={() => undefined}
    />,
  );
}

describe('prerequisite import snapshot', () => {
  it('renders immutable metadata, inference caveat, and the original historical answer', () => {
    renderMessages([prerequisiteMessage()]);

    const snapshot = screen.getByRole('region', { name: /prerequisite snapshot/i });
    expect(within(snapshot).getByText('Results')).toBeInTheDocument();
    expect(within(snapshot).getByText('Understand the paper methods')).toBeInTheDocument();
    expect(within(snapshot).getByText('qwen-local')).toBeInTheDocument();
    expect(within(snapshot).getByText(/model-inferred/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/not verified prerequisites/i)).toBeInTheDocument();
    expect(screen.getByText(/Not yet/)).toBeInTheDocument();
    expect(screen.queryByText(/CV TEXT MUST NOT APPEAR/)).not.toBeInTheDocument();
  });

  it('links only known in-range pages for the matching ready source file', () => {
    renderMessages(
      [prerequisiteMessage()],
      [{ id: 'paper-a', name: 'paper.pdf', status: 'ready', page_count: 10, parser: 'docling' }],
    );

    expect(screen.getByRole('link', { name: 'Page 2' })).toHaveAttribute(
      'href',
      '/api/topics/topic-a/files/paper-a/original#page=2',
    );
    expect(screen.getByRole('link', { name: 'Page 4' })).toBeInTheDocument();
    expect(screen.getByText('Page 11 unavailable')).toBeInTheDocument();
  });

  it.each([
    ['missing file', []],
    [
      'processing file',
      [{ id: 'paper-a', name: 'paper.pdf', status: 'processing', page_count: 10, parser: 'docling' }],
    ],
    [
      'unknown page bound',
      [{ id: 'paper-a', name: 'paper.pdf', status: 'ready', page_count: null, parser: 'docling' }],
    ],
  ])('marks source pages unavailable for a %s', (_case, files) => {
    renderMessages([prerequisiteMessage()], files as LabFile[]);

    expect(screen.queryByRole('link', { name: 'Page 2' })).not.toBeInTheDocument();
    expect(screen.getAllByText('Page unavailable').length).toBeGreaterThan(0);
  });

  it('does not link metadata from another topic and keeps legacy messages visible', () => {
    const foreignTopic = prerequisiteMessage({
      prerequisite_import: {
        ...prerequisiteMessage().prerequisite_import,
        topic_id: 'topic-b',
      },
    });
    renderMessages(
      [{ role: 'assistant', content: 'Existing response', summary_import: null }, foreignTopic],
      [{ id: 'paper-a', name: 'paper.pdf', status: 'ready', page_count: 10, parser: 'docling' }],
    );

    expect(screen.getByText('Existing response')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Page 2' })).not.toBeInTheDocument();
    expect(screen.getByText('Page unavailable')).toBeInTheDocument();
  });
});
