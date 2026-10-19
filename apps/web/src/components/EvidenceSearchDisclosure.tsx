import type { EvidenceSearchMetadata } from '../api/types';
import { summarizeEvidenceSearch } from '../domain/evidenceSearch';

function countLabel(count: number, singular: string): string {
  return `${count} ${singular}${count === 1 ? '' : 's'}`;
}

function summaryText(
  outcome: NonNullable<ReturnType<typeof summarizeEvidenceSearch>>['outcome'],
  summary: NonNullable<ReturnType<typeof summarizeEvidenceSearch>>,
) {
  switch (outcome) {
    case 'direct_answer':
      return summary.lookupCount === 0
        ? 'No follow-up search was made.'
        : `${countLabel(summary.lookupCount, 'lookup')} ran before the answer.`;
    case 'searched':
      switch (summary.followUp) {
        case 'no_results':
          return 'The search returned no additional passages.';
        case 'duplicates':
          return 'The search returned only passages already present in the original context.';
        case 'trimmed':
          return `The search found ${countLabel(summary.novelReturnedCount, 'new passage')}, but none fit in the final answer context.`;
        case 'retained':
          return `The search added ${countLabel(summary.retainedNewCount, 'new passage')} to the context sent for the answer.`;
        case 'none':
          return 'The search completed without adding passages.';
      }
    case 'invalid_action_fallback':
      return summary.lookupCount === 0
        ? 'No follow-up search was made because the search request could not be used.'
        : `The search request could not be used after ${countLabel(summary.lookupCount, 'lookup')}.`;
    case 'cancelled':
      return summary.lookupCount === 0
        ? 'The extra search stopped before a lookup.'
        : `The extra search stopped after ${countLabel(summary.lookupCount, 'lookup')}.`;
    case 'error':
      return summary.lookupCount === 0
        ? 'The extra search did not complete before a lookup.'
        : `The extra search did not complete after ${countLabel(summary.lookupCount, 'lookup')}.`;
    case 'in_progress':
      return summary.lookupCount === 0
        ? 'The saved search did not finish.'
        : `The saved search did not finish after ${countLabel(summary.lookupCount, 'lookup')}.`;
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
      <p>{summaryText(summary.outcome, summary)}</p>
      {summary.finalRetainedCount > 0 && citationCount === 0 && (
        <p>
          Answer context included {countLabel(summary.finalRetainedCount, 'passage')}; source details are unavailable.
        </p>
      )}
      {summary.warning && <p className="evidence-search-warning">{summary.warning}</p>}
    </section>
  );
}
