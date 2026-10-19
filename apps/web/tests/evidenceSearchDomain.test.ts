import { describe, expect, test } from 'vitest';
import directCapture from './fixtures/evidenceSearch/direct.json';
import searchCapture from './fixtures/evidenceSearch/search.json';
import invalidCapture from './fixtures/evidenceSearch/invalid.json';
import { foldEvidenceSearchProgress, summarizeEvidenceSearch } from '../src/domain/evidenceSearch';
import { messagesResponseSchema, streamEventSchema, type EvidenceSearchMetadata } from '../src/api/types';
import type { EvidenceSearchProgress } from '../src/domain/evidenceSearch';

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('Expected a captured object.');
  }
  return value as Record<string, unknown>;
}

function metadata(capture: unknown): EvidenceSearchMetadata {
  const saved = messagesResponseSchema.parse(asRecord(capture).saved);
  const value = saved.messages[1]?.retrieval?.evidence_search;
  if (!value) throw new Error('Captured answer is missing evidence-search metadata.');
  return value;
}

describe('evidence-search domain', () => {
  test('progress is a separate ephemeral fold and terminal events clear it', () => {
    let progress: EvidenceSearchProgress | null = null;
    const deciding = streamEventSchema.parse({ type: 'evidence_status', stage: 'deciding' });
    const searching = streamEventSchema.parse({
      type: 'evidence_status',
      stage: 'searching',
      warning: 'A safe progress warning.',
    });
    progress = foldEvidenceSearchProgress(progress, deciding);
    expect(progress).toEqual({ stage: 'deciding' });
    progress = foldEvidenceSearchProgress(progress, searching);
    expect(progress).toEqual({ stage: 'searching', warning: 'A safe progress warning.' });
    expect(foldEvidenceSearchProgress(progress, { type: 'thinking', text: 'private model reasoning' })).toEqual(
      progress,
    );
    expect(foldEvidenceSearchProgress(progress, { type: 'done' })).toBeNull();
    expect(foldEvidenceSearchProgress(progress, { type: 'error', message: 'failed' })).toBeNull();
  });

  test('summary distinguishes retained new evidence and declared labels from supplied sources', () => {
    expect(summarizeEvidenceSearch(metadata(searchCapture))).toMatchObject({
      outcome: 'searched',
      followUp: 'retained',
      initialAvailableCount: 1,
      initialRetainedCount: 1,
      returnedCount: 1,
      novelReturnedCount: 1,
      retainedNewCount: 1,
      finalRetainedCount: 2,
      declaredSourceLabels: [],
    });
    expect(summarizeEvidenceSearch(metadata(directCapture))).toMatchObject({
      outcome: 'direct_answer',
      followUp: 'none',
      declaredSourceLabels: ['E1'],
      finalRetainedCount: 1,
    });
    expect(summarizeEvidenceSearch(metadata(invalidCapture))).toMatchObject({
      outcome: 'invalid_action_fallback',
      followUp: 'none',
      warning: 'The structured planning response was unusable; no additional search was performed.',
    });
  });

  test('summary separates duplicate-only, no-hit and trimmed-new search outcomes', () => {
    const initialId = metadata(searchCapture).initial_available_chunk_ids[0];
    if (!initialId) throw new Error('Search fixture is missing its initial source.');
    const duplicate = structuredClone(metadata(searchCapture));
    duplicate.returned_chunk_ids = [initialId];
    duplicate.new_chunk_ids = [];
    duplicate.retained_new_chunk_ids = [];
    duplicate.final_chunk_ids = [initialId];
    expect(summarizeEvidenceSearch(duplicate)?.followUp).toBe('duplicates');

    const noHits = structuredClone(metadata(searchCapture));
    noHits.returned_chunk_ids = [];
    noHits.new_chunk_ids = [];
    noHits.retained_new_chunk_ids = [];
    noHits.final_chunk_ids = [initialId];
    expect(summarizeEvidenceSearch(noHits)?.followUp).toBe('no_results');

    const trimmed = structuredClone(metadata(searchCapture));
    trimmed.retained_new_chunk_ids = [];
    trimmed.final_chunk_ids = [initialId];
    expect(summarizeEvidenceSearch(trimmed)?.followUp).toBe('trimmed');
    expect(summarizeEvidenceSearch(null)).toBeNull();
  });
});
