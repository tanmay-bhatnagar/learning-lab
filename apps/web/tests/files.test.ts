import { describe, expect, test } from 'vitest';
import { fileMeta, isSelectable, showLegacyUnassessedWarning } from '../src/domain/files';

describe('files domain', () => {
  test('isSelectable rejects processing and error records', () => {
    expect(isSelectable({ id: '1', name: 'a.pdf', status: 'ready', parser: 'docling' })).toBe(true);
    expect(isSelectable({ id: '1', name: 'a.pdf', status: 'processing', parser: 'docling' })).toBe(false);
    expect(isSelectable({ id: '1', name: 'a.pdf', status: 'ready', parser: 'docling', error: 'bad' })).toBe(false);
  });

  test('fileMeta joins parser, status and counts', () => {
    expect(
      fileMeta({
        id: '1',
        name: 'a.pdf',
        status: 'ready',
        parser: 'docling',
        index_mode: 'hybrid',
        page_count: 2,
        asset_count: 1,
      }),
    ).toBe('docling · ready · hybrid index · 2 pages · 1 visual');
  });

  test('showLegacyUnassessedWarning flags ready files without diagnostics', () => {
    expect(showLegacyUnassessedWarning({ id: '1', name: 'a.pdf', status: 'ready', parser: 'docling' })).toBe(true);
    expect(
      showLegacyUnassessedWarning({
        id: '1',
        name: 'a.pdf',
        status: 'ready',
        parser: 'docling',
        extraction_diagnostics: { status: 'unassessed', note: '', findings: [] },
      }),
    ).toBe(false);
  });
});
