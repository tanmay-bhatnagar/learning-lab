import type { LabFile } from '../api/types';
import type { MapSection } from '../api/documentMap';

export function mapUnavailableReason(file: LabFile): string | null {
  if (file.status !== 'ready') return 'not ready';
  if (file.parser !== 'docling' || !file.docling_name) return 'requires a Docling parse';
  return null;
}

export function findMapSection(sections: MapSection[], id: string): MapSection | null {
  for (const section of sections) {
    if (section.id === id) return section;
    const nested = findMapSection(section.children, id);
    if (nested) return nested;
  }
  return null;
}

export function mapSectionUnits(section: MapSection, units: DocumentMapUnit[]): DocumentMapUnit[] {
  const byId = new Map(units.map((unit) => [unit.id, unit]));
  return section.source_unit_ids.flatMap((id) => {
    const unit = byId.get(id);
    return unit ? [unit] : [];
  });
}

type DocumentMapUnit = { id: string; pages: number[]; included: boolean; warnings: string[] };
