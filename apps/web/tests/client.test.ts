import { describe, expect, test } from 'vitest';
import { parseErrorDetail } from '../src/api/client';

describe('api client', () => {
  test('parseErrorDetail stringifies structured FastAPI detail arrays', () => {
    expect(parseErrorDetail({ detail: 'Topic missing' }, 'fallback')).toBe('Topic missing');
    expect(parseErrorDetail({ detail: [{ msg: 'bad field' }] }, 'fallback')).toBe(
      JSON.stringify([{ msg: 'bad field' }]),
    );
    expect(parseErrorDetail({}, 'fallback')).toBe('fallback');
  });
});
