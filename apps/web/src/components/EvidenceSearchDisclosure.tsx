import type { EvidenceSearchMetadata } from '../api/types';
import type { EvidenceSearchFollowUp, EvidenceSearchSummary } from '../domain/evidenceSearch';
import { summarizeEvidenceSearch } from '../domain/evidenceSearch';

function countLabel(count: number, singular: string): string {
  return `${count} ${singular}${count === 1 ? '' : 's'}`;
}

function searchedSummaryText(summary: EvidenceSearchSummary): string {
  const descriptions: Record<EvidenceSearchFollowUp, string> = {
    none: 'The extra search completed without adding passages.',
    no_results: 'The extra search found no additional passages.',
    duplicates: 'The extra search returned passages already found for this question.',
    trimmed: `The extra search found ${countLabel(summary.novelReturnedCount, 'new passage')}, but none fit in the final answer context.`,
    retained: `The extra search added ${countLabel(summary.retainedNewCount, 'new passage')} to the context sent for the answer.`,
  };
  return descriptions[summary.followUp];
}

function summaryText(summary: EvidenceSearchSummary): string {
  switch (summary.outcome) {
    case 'direct_answer':
      return summary.lookupCount === 0 ? 'No follow-up search was made.' : 'An extra search ran before the answer.';
    case 'searched':
      return searchedSummaryText(summary);
    case 'invalid_action_fallback':
      return summary.lookupCount === 0
        ? 'The extra search request could not be used, so no extra search was made.'
        : `The extra search request could not be used after ${countLabel(summary.lookupCount, 'extra search attempt')}.`;
    case 'cancelled':
      return summary.lookupCount === 0
        ? 'The response stopped before an extra search.'
        : `The response stopped after ${countLabel(summary.lookupCount, 'extra search attempt')}.`;
    case 'error':
      return summary.lookupCount === 0
        ? 'The response did not finish before an extra search.'
        : `The response did not finish after ${countLabel(summary.lookupCount, 'extra search attempt')}.`;
    case 'in_progress':
      return summary.lookupCount === 0
        ? 'The response did not finish.'
        : `The response did not finish after ${countLabel(summary.lookupCount, 'extra search attempt')}.`;
  }
}

export function EvidenceSearchDisclosure({
  metadata,
  citationCount,
}: {
  metadata?: EvidenceSearchMetadata | null;
  citationCount: number;
}) {
  const summary = summarizeEvidenceSearch(metadata);
  if (!summary) return null;

  return (
    <section className="evidence-search-disclosure" aria-label="Extra search summary">
      <strong>Extra search</strong>
      <p>{summaryText(summary)}</p>
      {summary.finalRetainedCount > 0 && citationCount === 0 && (
        <p>
          Answer context included {countLabel(summary.finalRetainedCount, 'passage')}; source details are unavailable.
        </p>
      )}
      {summary.warning && summary.outcome !== 'invalid_action_fallback' && (
        <p className="evidence-search-warning">{summary.warning}</p>
      )}
    </section>
  );
}
