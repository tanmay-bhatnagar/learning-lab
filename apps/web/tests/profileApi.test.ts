import { afterEach, describe, expect, test, vi } from 'vitest';
import {
  createProficiencyEntry,
  cvOriginalUrl,
  getCvText,
  getProfile,
  getProficiency,
  profileSchema,
  proficiencySchema,
  revokeCv,
  saveProficiencyBatch,
  selectCv,
  updateProficiencyEntry,
  uploadCv,
} from '../src/api/profile';

const cvId = 'a'.repeat(32);
const manualId = 'b'.repeat(32);
const requirementId = 'c'.repeat(32);

const cvRecord = {
  id: cvId,
  original_name: 'Research CV.pdf',
  status: 'ready',
  revoked: false,
  parser: 'docling',
  parser_version: '2.55.1',
  original_sha256: '1'.repeat(64),
  extracted_sha256: '2'.repeat(64),
  native_document_sha256: null,
  extraction_diagnostics: { status: 'ready', findings: [], note: 'Extraction fidelity is unassessed.' },
  created_at: '2026-10-12T10:00:00Z',
};

const profilePayload = {
  schema_version: 1,
  revision: 3,
  active_cv_id: cvId,
  cvs: [cvRecord],
};

const proficiencyPayload = {
  schema_version: 1,
  revision: 7,
  entries: [
    {
      id: manualId,
      concept: 'Basic Python',
      comfort: 'comfortable',
      notes: 'Used for small scripts.',
      source_kind: 'user_manual',
      updated_at: '2026-10-12T10:05:00Z',
    },
    {
      id: requirementId,
      concept: 'Linear algebra',
      comfort: null,
      notes: '',
      source_kind: 'model_requirement',
      topic_id: 'synthetic-topic',
      assessment_id: 'synthetic-assessment',
      requirement_id: 'synthetic-requirement',
    },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe('profile wire schemas', () => {
  test('accepts the versioned shared profile with exact filename and parser provenance', () => {
    expect(profileSchema.parse(profilePayload)).toEqual(profilePayload);
  });

  test('accepts a pending model requirement separately from explicit manual comfort', () => {
    const parsed = proficiencySchema.parse(proficiencyPayload);
    expect(parsed.entries[0]).toMatchObject({ source_kind: 'user_manual', comfort: 'comfortable' });
    expect(parsed.entries[1]).toMatchObject({ source_kind: 'model_requirement', comfort: null });
  });

  test('rejects unsupported versions, malformed revisions, unknown provenance and invalid comfort values', () => {
    expect(profileSchema.safeParse({ ...profilePayload, schema_version: 2 }).success).toBe(false);
    expect(profileSchema.safeParse({ ...profilePayload, revision: -1 }).success).toBe(false);
    expect(
      proficiencySchema.safeParse({
        ...proficiencyPayload,
        entries: [{ ...proficiencyPayload.entries[0], source_kind: 'cv_claim' }],
      }).success,
    ).toBe(false);
    expect(
      proficiencySchema.safeParse({
        ...proficiencyPayload,
        entries: [{ ...proficiencyPayload.entries[0], comfort: null }],
      }).success,
    ).toBe(false);
  });
});

describe('profile API functions', () => {
  test('loads profile and proficiency through their versioned GET endpoints', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return url.endsWith('/profile/proficiency') ? Response.json(proficiencyPayload) : Response.json(profilePayload);
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(getProfile()).resolves.toEqual(profilePayload);
    await expect(getProficiency()).resolves.toEqual(proficiencyPayload);
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual(['/api/profile', '/api/profile/proficiency']);
  });

  test('uploads the selected file, exact original filename and parser as multipart fields', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = init?.body as FormData;
      expect(init?.method).toBe('POST');
      expect(init?.headers).toBeUndefined();
      expect(body.get('original_name')).toBe('Tanmay Research CV.pdf');
      expect(body.get('parser')).toBe('docling');
      expect(body.get('file')).toBeInstanceOf(File);
      return Response.json({ ...cvRecord, original_name: 'Tanmay Research CV.pdf', revision: 4 }, { status: 201 });
    });
    vi.stubGlobal('fetch', fetchMock);

    const file = new File(['%PDF-synthetic'], 'resume.pdf', { type: 'application/pdf' });
    await expect(uploadCv(file, 'Tanmay Research CV.pdf', 'docling')).resolves.toMatchObject({ revision: 4 });
    expect(fetchMock).toHaveBeenCalledWith('/api/profile/cvs', expect.any(Object));
  });

  test('reads complete extracted text and builds an encoded original-file URL', async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({
        id: cvId,
        original_name: 'Research CV.pdf',
        parser: 'docling',
        parser_version: '2.55.1',
        text: 'Synthetic complete extracted CV text.',
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(getCvText(cvId)).resolves.toMatchObject({ text: 'Synthetic complete extracted CV text.' });
    expect(fetchMock).toHaveBeenCalledWith(`/api/profile/cvs/${cvId}/text`, expect.any(Object));
    expect(cvOriginalUrl('cv / one')).toBe('/api/profile/cvs/cv%20%2F%20one/original');
  });

  test('selects and revokes a CV using optimistic profile revision', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe('POST');
      expect(JSON.parse(String(init?.body))).toEqual({ expected_revision: 3 });
      return Response.json(profilePayload);
    });
    vi.stubGlobal('fetch', fetchMock);

    await selectCv(cvId, 3);
    await revokeCv(cvId, 3);
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      `/api/profile/cvs/${cvId}/select`,
      `/api/profile/cvs/${cvId}/revoke`,
    ]);
  });

  test('creates and updates manual proficiency with expected revisions and notes field', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      expect(body.expected_revision).toBe(7);
      expect(body.notes).toBe('A synthetic learner note.');
      return Response.json(proficiencyPayload, { status: 201 });
    });
    vi.stubGlobal('fetch', fetchMock);

    await createProficiencyEntry({
      concept: 'Statistics',
      comfort: 'refresher',
      notes: 'A synthetic learner note.',
      expected_revision: 7,
    });
    await updateProficiencyEntry(manualId, { notes: 'A synthetic learner note.', expected_revision: 7 });
    expect(fetchMock.mock.calls.map(([input, init]) => [String(input), init?.method])).toEqual([
      ['/api/profile/proficiency/entries', 'POST'],
      [`/api/profile/proficiency/entries/${manualId}`, 'PATCH'],
    ]);
  });

  test('saves manual additions and requirement answers in one revision-checked PUT', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe('PUT');
      expect(JSON.parse(String(init?.body))).toEqual({
        expected_revision: 7,
        additions: [{ concept: 'Probability', comfort: 'refresher', notes: 'Synthetic note.' }],
        updates: [{ id: requirementId, comfort: null }],
      });
      return Response.json(proficiencyPayload);
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      saveProficiencyBatch({
        expected_revision: 7,
        additions: [{ concept: 'Probability', comfort: 'refresher', notes: 'Synthetic note.' }],
        updates: [{ id: requirementId, comfort: null }],
      }),
    ).resolves.toEqual(proficiencyPayload);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/profile/proficiency', expect.any(Object));
  });

  test('exposes malformed successful payloads instead of returning unvalidated state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ ...profilePayload, revision: 'wrong' })),
    );
    await expect(getProfile()).rejects.toThrow(/Invalid \/profile/);
  });
});
