import type { LabFile } from '../api/types';
import { assetApiUrl } from '../api';
import { resolveAssetId } from '../retrievalTraceHelpers';

export function VisualAssets({
  topic,
  file,
  assetRefs,
  classNamePrefix = 'citation',
}: {
  topic: string;
  file: LabFile | undefined;
  assetRefs: string[];
  classNamePrefix?: 'citation' | 'trace';
}) {
  if (!assetRefs.length) return null;
  const groupClass = `${classNamePrefix}-assets`;
  const itemClass = `${classNamePrefix}-asset`;
  const missingClass = `${itemClass} ${itemClass}-missing`;
  const placeholderClass = `${classNamePrefix}-asset-placeholder`;
  return (
    <div className={groupClass} aria-label="Linked visuals">
      {assetRefs.map((ref) => {
        const assetId = resolveAssetId(file, ref);
        const asset = file?.assets?.find((item) => item.id === assetId || item.name === ref);
        const key = assetId ?? `${ref}-${asset?.name ?? 'missing'}`;
        if (!assetId || !file) {
          return (
            <figure className={missingClass} key={key}>
              <span className={placeholderClass}>Visual unavailable</span>
              <figcaption>{asset?.caption || ref}</figcaption>
            </figure>
          );
        }
        const url = assetApiUrl(topic, file.id, assetId);
        return (
          <figure className={itemClass} key={key}>
            <a href={url} target="_blank" rel="noopener noreferrer">
              <img src={url} alt={asset?.caption || asset?.kind || 'Document visual'} loading="lazy" />
            </a>
            <figcaption>
              {asset?.caption || `${asset?.kind || 'visual'}${asset?.page != null ? ` · p.${asset.page}` : ''}`}
            </figcaption>
          </figure>
        );
      })}
    </div>
  );
}
