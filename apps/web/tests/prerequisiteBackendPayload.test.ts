import { describe, expect, test } from 'vitest';
import { prerequisiteStateSchema } from '../src/api/prerequisites';
import actual from './fixtures/prerequisites-api-contract.json';

describe('captured real local prerequisite payload', () => {
  test('accepts the actual Docling/Ollama completed-state response without remapping', () => {
    expect(prerequisiteStateSchema.parse(actual)).toEqual(actual);
    expect(
      actual.current_assessment.requirements.every((row) => row.comfort === null && row.comfort_status === 'pending'),
    ).toBe(true);
  });
});
