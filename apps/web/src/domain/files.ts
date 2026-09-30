import type { LabFile } from '../api/types';

const NON_SELECTABLE_STATUS = /failed|error|pending|processing|queued|converting|uploaded/i;

export function isSelectable(file: LabFile): boolean {
  return !file.error && !NON_SELECTABLE_STATUS.test(file.status);
}

export function fileMeta(file: LabFile): string {
  const parts = [file.parser, file.status];
  if (file.index_mode) parts.push(`${file.index_mode} index`);
  if (file.page_count != null) parts.push(`${file.page_count} page${file.page_count === 1 ? '' : 's'}`);
  if (file.asset_count != null) parts.push(`${file.asset_count} visual${file.asset_count === 1 ? '' : 's'}`);
  return parts.join(' · ');
}

export function diagnosticLabel(file: LabFile): string | null {
  if (file.extraction_diagnostics) {
    return file.extraction_diagnostics.status.replace('_', ' ');
  }
  if (file.status === 'ready') return 'unassessed';
  return null;
}

export function showLegacyUnassessedWarning(file: LabFile): boolean {
  return !file.extraction_diagnostics && file.status === 'ready';
}
