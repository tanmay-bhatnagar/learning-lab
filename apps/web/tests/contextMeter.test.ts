import { describe, expect, test } from 'vitest';
import { contextMeter } from '../src/domain/contextMeter';

describe('contextMeter', () => {
  test('computes percent and labels from context and settings', () => {
    expect(
      contextMeter({}, { model: 'm', context_limit: 1000, parser: 'docling', embedding_model: 'e', retrieval_top_k: 6 })
        .used,
    ).toBeUndefined();
    const filled = contextMeter(
      { used: 250, limit: 1000, estimated: true },
      {
        model: 'm',
        context_limit: 2000,
        parser: 'docling',
        embedding_model: 'e',
        retrieval_top_k: 6,
      },
    );
    expect(filled.percent).toBe(25);
    expect(filled.limit).toBe(1000);
    expect(filled.label).toBe('~250 / 1,000');
  });
});
