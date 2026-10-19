import { createRef } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import directCapture from './fixtures/evidenceSearch/direct.json';
import searchCapture from './fixtures/evidenceSearch/search.json';
import { messagesResponseSchema, type LabFile, type Message } from '../src/api/types';
import { MessageList } from '../src/components/MessageList';

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('Expected a captured object.');
  }
  return value as Record<string, unknown>;
}

function savedAnswer(capture: unknown): Message {
  const saved = messagesResponseSchema.parse(asRecord(capture).saved);
  const message = saved.messages[1];
  if (!message) throw new Error('Capture has no assistant answer.');
  return message;
}

function renderAnswer(message: Message, files: LabFile[] = []) {
  return render(
    <MessageList
      messages={[message]}
      models={[]}
      topic="topic-a"
      files={files}
      sending={false}
      bottomRef={createRef<HTMLDivElement>()}
      onStarterPrompt={vi.fn()}
    />,
  );
}

describe('extra-search answer presentation', () => {
  test('keeps a direct-answer disclosure visible even when saved citations are empty', () => {
    const message = structuredClone(savedAnswer(directCapture));
    if (!message.retrieval) throw new Error('Direct capture has no retrieval record.');
    message.retrieval.citations = [];
    renderAnswer(message);

    expect(screen.getByLabelText('Extra search summary')).toHaveTextContent(/No follow-up search was made/i);
  });

  test('shows readable source labels and pages without implying semantic support', () => {
    const message = savedAnswer(searchCapture);
    const citations = message.retrieval?.citations ?? [];
    const files = [...new Map(citations.map((citation) => [citation.file_id, citation])).values()].map((citation) => ({
      id: citation.file_id,
      name: citation.file_name,
      status: 'ready',
      parser: 'docling',
      page_count: 3,
    }));
    renderAnswer(message, files);

    expect(screen.getByLabelText('Extra search summary')).toHaveTextContent(/retained 1 additional passage/i);
    expect(screen.getByLabelText('Extra search summary')).not.toHaveTextContent(/used|supported/i);
    fireEvent.click(screen.getByRole('button', { name: /Sources \(2\)/i }));
    expect(screen.getByRole('heading', { name: /E1.*paper\.pdf/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /E2.*validation\.pdf/i })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Page 1' })).toHaveLength(2);
  });

  test.each([
    ['duplicates', 'already found for this question'],
    ['no results', 'found no additional passages'],
    ['trimmed', 'none fit in the final answer context'],
  ])('describes %s without claiming source support', (_name, description) => {
    const message = structuredClone(savedAnswer(searchCapture));
    const metadata = message.retrieval?.evidence_search;
    if (!metadata) throw new Error('Search capture has no saved metadata.');
    const firstInitial = metadata.initial_available_chunk_ids[0];
    const newId = metadata.new_chunk_ids[0];
    if (!firstInitial || !newId) throw new Error('Search capture is missing source identities.');

    if (_name === 'duplicates') {
      metadata.returned_chunk_ids = [firstInitial];
      metadata.new_chunk_ids = [];
      metadata.retained_new_chunk_ids = [];
      metadata.final_chunk_ids = [firstInitial];
    } else if (_name === 'no results') {
      metadata.returned_chunk_ids = [];
      metadata.new_chunk_ids = [];
      metadata.retained_new_chunk_ids = [];
      metadata.final_chunk_ids = [firstInitial];
    } else {
      metadata.retained_new_chunk_ids = [];
      metadata.final_chunk_ids = [firstInitial];
    }

    renderAnswer(message);
    expect(screen.getByLabelText('Extra search summary')).toHaveTextContent(description);
    expect(screen.getByLabelText('Extra search summary')).not.toHaveTextContent(/used|supported/i);
  });

  test.each([
    ['cancelled', 1, 'Response stopped during an extra search after 1 search check.'],
    ['error', 0, 'Response did not finish before an extra search.'],
  ] as const)('reports %s using the actual number of search checks', (_outcome, checks, description) => {
    const message = structuredClone(savedAnswer(searchCapture));
    const metadata = message.retrieval?.evidence_search;
    if (!metadata) throw new Error('Search capture has no saved metadata.');
    metadata.outcome = _outcome;
    metadata.lookup_count = checks;
    metadata.warning = null;

    renderAnswer(message);
    expect(screen.getByLabelText('Extra search summary')).toHaveTextContent(description);
  });

  test('translates invalid-action fallback without showing internal planning warnings', () => {
    const message = savedAnswer(searchCapture);
    const metadata = message.retrieval?.evidence_search;
    if (!metadata) throw new Error('Search capture has no saved metadata.');
    metadata.outcome = 'invalid_action_fallback';
    metadata.warning = 'The structured planning response was unusable; no additional search was performed.';
    metadata.lookup_count = 0;

    renderAnswer(message);
    expect(screen.getByLabelText('Extra search summary')).toHaveTextContent(
      'The extra search request could not be used, so no extra search was made.',
    );
    expect(screen.getByLabelText('Extra search summary')).not.toHaveTextContent(/structured planning response/i);
  });
});
