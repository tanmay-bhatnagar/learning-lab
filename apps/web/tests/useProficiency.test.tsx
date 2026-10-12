import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import * as profileApi from '../src/api/profile';
import type { Profile, ProfileCv, ProficiencyState } from '../src/api/profile';
import type { ProficiencyDraft } from '../src/domain/proficiency';
import { useProficiency } from '../src/hooks/useProficiency';

const cvOneId = 'a'.repeat(32);
const cvTwoId = 'd'.repeat(32);
const manualId = 'b'.repeat(32);
const requirementEntryId = 'c'.repeat(32);

const cvRecord = (id: string, filename: string): ProfileCv => ({
  id,
  original_name: filename,
  status: 'ready',
  revoked: false,
  parser: 'docling',
  parser_version: '2.55.1',
  original_sha256: '1'.repeat(64),
  extracted_sha256: '2'.repeat(64),
  native_document_sha256: null,
  extraction_diagnostics: { status: 'ready', findings: [], note: 'Extraction fidelity is unassessed.' },
  created_at: '2026-10-12T10:00:00Z',
});

const emptyProfile: Profile = { schema_version: 1, revision: 0, active_cv_id: null, cvs: [] };
const emptyProficiency: ProficiencyState = { schema_version: 1, revision: 0, entries: [] };

const populatedProficiency: ProficiencyState = {
  schema_version: 1,
  revision: 5,
  entries: [
    {
      id: manualId,
      concept: 'Python',
      comfort: 'refresher',
      notes: 'Old note.',
      source_kind: 'user_manual',
      updated_at: '2026-10-12T10:00:00Z',
    },
    {
      id: requirementEntryId,
      concept: 'Statistics',
      comfort: null,
      notes: '',
      source_kind: 'model_requirement',
      topic_id: 'synthetic-topic',
      assessment_id: 'synthetic-assessment',
      requirement_id: 'req-statistics',
    },
  ],
};

afterEach(() => vi.restoreAllMocks());

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

describe('useProficiency', () => {
  test('a CV profile load error does not block manual proficiency load and save', async () => {
    vi.spyOn(profileApi, 'getProfile').mockRejectedValue(new Error('Shared CV profile is unavailable.'));
    vi.spyOn(profileApi, 'getProficiency').mockResolvedValue(emptyProficiency);
    const saved: ProficiencyState = {
      schema_version: 1,
      revision: 1,
      entries: [
        {
          id: manualId,
          concept: 'Python',
          comfort: 'new',
          notes: '',
          source_kind: 'user_manual',
          updated_at: '2026-10-13T00:00:00Z',
        },
      ],
    };
    const saveBatch = vi.spyOn(profileApi, 'saveProficiencyBatch').mockResolvedValue(saved);
    const { result } = renderHook(() => useProficiency('docling'));
    await waitFor(() => expect(result.current.proficiency).toEqual(emptyProficiency));
    expect(result.current.profileError).toMatch(/Shared CV profile is unavailable/);

    const draft: ProficiencyDraft = {
      id: 'manual:temporary',
      concept: 'Python',
      comfort: 'new',
      note: '',
      kind: 'manual',
    };
    await act(async () => result.current.saveProficiency([draft]));

    expect(saveBatch).toHaveBeenCalledWith({
      expected_revision: 0,
      additions: [{ concept: 'Python', comfort: 'new', notes: '' }],
      updates: [],
    });
    expect(result.current.proficiency).toEqual(saved);
  });

  test('saves manual and per-requirement edits in one atomic request and adopts its validated response', async () => {
    vi.spyOn(profileApi, 'getProfile').mockResolvedValue(emptyProfile);
    vi.spyOn(profileApi, 'getProficiency').mockResolvedValue(populatedProficiency);
    const saved: ProficiencyState = {
      schema_version: 1,
      revision: 6,
      entries: [
        { ...populatedProficiency.entries[0], comfort: 'comfortable', notes: 'Updated note.' },
        { ...populatedProficiency.entries[1], comfort: 'new' },
        {
          id: 'e'.repeat(32),
          concept: 'Probability',
          comfort: 'refresher',
          notes: 'Added manually.',
          source_kind: 'user_manual',
          updated_at: '2026-10-13T00:00:00Z',
        },
      ],
    };
    const saveBatch = vi.spyOn(profileApi, 'saveProficiencyBatch').mockResolvedValue(saved);
    const createSingle = vi.spyOn(profileApi, 'createProficiencyEntry');
    const updateSingle = vi.spyOn(profileApi, 'updateProficiencyEntry');
    const { result } = renderHook(() => useProficiency('docling'));
    await waitFor(() => expect(result.current.proficiency).toEqual(populatedProficiency));

    const drafts: ProficiencyDraft[] = [
      {
        id: manualId,
        concept: 'Python',
        comfort: 'comfortable',
        note: 'Updated note.',
        kind: 'manual',
      },
      {
        id: 'manual:temporary',
        concept: 'Probability',
        comfort: 'refresher',
        note: 'Added manually.',
        kind: 'manual',
      },
      {
        id: requirementEntryId,
        concept: 'Statistics',
        comfort: 'new',
        note: '',
        kind: 'requirement',
        requirementId: 'req-statistics',
      },
    ];
    await act(async () => result.current.saveProficiency(drafts));

    expect(saveBatch).toHaveBeenCalledTimes(1);
    expect(saveBatch).toHaveBeenCalledWith({
      expected_revision: 5,
      additions: [{ concept: 'Probability', comfort: 'refresher', notes: 'Added manually.' }],
      updates: [
        { id: manualId, concept: 'Python', comfort: 'comfortable', notes: 'Updated note.' },
        { id: requirementEntryId, comfort: 'new' },
      ],
    });
    expect(createSingle).not.toHaveBeenCalled();
    expect(updateSingle).not.toHaveBeenCalled();
    expect(result.current.proficiency).toEqual(saved);
  });

  test('uses the current parser for the exact renamed upload and surfaces an extraction failure', async () => {
    const failedCv: ProfileCv = {
      ...cvRecord('f'.repeat(32), 'Renamed CV.pdf'),
      status: 'error',
      extracted_sha256: null,
      extraction_diagnostics: { status: 'error', findings: ['No text was extracted.'] },
    };
    vi.spyOn(profileApi, 'getProfile')
      .mockResolvedValueOnce(emptyProfile)
      .mockResolvedValue({ ...emptyProfile, revision: 1, cvs: [failedCv] });
    vi.spyOn(profileApi, 'getProficiency').mockResolvedValue(emptyProficiency);
    const upload = vi.spyOn(profileApi, 'uploadCv').mockResolvedValue({ ...failedCv, revision: 1 });
    const { result } = renderHook(() => useProficiency('anydoc'));
    await waitFor(() => expect(result.current.profile).toEqual(emptyProfile));

    const file = new File(['%PDF-synthetic'], 'original.pdf', { type: 'application/pdf' });
    await act(async () => result.current.uploadCv(file, 'Renamed CV.pdf'));

    expect(upload).toHaveBeenCalledWith(file, 'Renamed CV.pdf', 'anydoc', expect.any(AbortSignal));
    expect(result.current.profile?.cvs[0]?.original_name).toBe('Renamed CV.pdf');
    expect(result.current.cvError).toMatch(/No text was extracted/);
    expect(result.current.proficiency).toEqual(emptyProficiency);
  });

  test('keeps a failed new CV extraction visible when the active CV preview refresh succeeds', async () => {
    const activeProfile: Profile = {
      schema_version: 1,
      revision: 1,
      active_cv_id: cvOneId,
      cvs: [cvRecord(cvOneId, 'Existing.pdf')],
    };
    const extractionFailedCv: ProfileCv = {
      ...cvRecord(cvTwoId, 'New CV.pdf'),
      status: 'error',
      extracted_sha256: null,
      extraction_diagnostics: { status: 'error', findings: ['No text was extracted.'] },
    };
    const profileAfterUpload: Profile = {
      ...activeProfile,
      revision: 2,
      cvs: [...activeProfile.cvs, extractionFailedCv],
    };
    const activeText: profileApi.CvText = {
      id: cvOneId,
      original_name: 'Existing.pdf',
      parser: 'docling',
      parser_version: '2.55.1',
      text: 'Existing active CV text.',
    };
    vi.spyOn(profileApi, 'getProfile').mockResolvedValueOnce(activeProfile).mockResolvedValue(profileAfterUpload);
    vi.spyOn(profileApi, 'getProficiency').mockResolvedValue(emptyProficiency);
    vi.spyOn(profileApi, 'getCvText').mockResolvedValue(activeText);
    vi.spyOn(profileApi, 'uploadCv').mockResolvedValue({ ...extractionFailedCv, revision: 2 });
    const { result } = renderHook(() => useProficiency('docling'));
    await waitFor(() => expect(result.current.cvText).toEqual(activeText));

    const file = new File(['%PDF-synthetic'], 'new.pdf', { type: 'application/pdf' });
    await act(async () => result.current.uploadCv(file, 'New CV.pdf'));

    expect(result.current.cvText).toEqual(activeText);
    expect(result.current.cvError).toMatch(/No text was extracted/);
  });

  test('aborts a late full-text preview when a newer CV selection becomes active', async () => {
    const profileOne: Profile = {
      schema_version: 1,
      revision: 1,
      active_cv_id: cvOneId,
      cvs: [cvRecord(cvOneId, 'First.pdf'), cvRecord(cvTwoId, 'Second.pdf')],
    };
    const profileTwo = { ...profileOne, revision: 2, active_cv_id: cvTwoId };
    const firstText = deferred<profileApi.CvText>();
    const secondCvText: profileApi.CvText = {
      id: cvTwoId,
      original_name: 'Second.pdf',
      parser: 'docling',
      parser_version: '2.55.1',
      text: 'Complete synthetic text for the second CV.',
    };
    vi.spyOn(profileApi, 'getProfile').mockResolvedValue(profileOne);
    vi.spyOn(profileApi, 'getProficiency').mockResolvedValue(emptyProficiency);
    const textRequest = vi
      .spyOn(profileApi, 'getCvText')
      .mockImplementation((id) => (id === cvOneId ? firstText.promise : Promise.resolve(secondCvText)));
    vi.spyOn(profileApi, 'selectCv').mockResolvedValue(profileTwo);
    const { result } = renderHook(() => useProficiency('docling'));
    await waitFor(() => expect(textRequest).toHaveBeenCalledWith(cvOneId, expect.any(AbortSignal)));
    const firstSignal = textRequest.mock.calls[0]?.[1];

    await act(async () => result.current.selectCv(cvTwoId));
    expect(firstSignal?.aborted).toBe(true);
    expect(result.current.cvText).toEqual(secondCvText);
    expect(textRequest).toHaveBeenCalledWith(cvTwoId, expect.any(AbortSignal));
    expect(profileApi.selectCv).toHaveBeenCalledWith(cvTwoId, 1, expect.any(AbortSignal));

    await act(async () =>
      firstText.resolve({
        id: cvOneId,
        original_name: 'First.pdf',
        parser: 'docling',
        parser_version: '2.55.1',
        text: 'Late text for first CV.',
      }),
    );
    expect(result.current.cvText).toEqual(secondCvText);
  });

  test('does not expose the previously selected CV text while the newly active CV preview is pending', async () => {
    const profileOne: Profile = {
      schema_version: 1,
      revision: 1,
      active_cv_id: cvOneId,
      cvs: [cvRecord(cvOneId, 'First.pdf'), cvRecord(cvTwoId, 'Second.pdf')],
    };
    const profileTwo = { ...profileOne, revision: 2, active_cv_id: cvTwoId };
    const secondText = deferred<profileApi.CvText>();
    const firstCvText: profileApi.CvText = {
      id: cvOneId,
      original_name: 'First.pdf',
      parser: 'docling',
      parser_version: '2.55.1',
      text: 'First CV text.',
    };
    vi.spyOn(profileApi, 'getProfile').mockResolvedValue(profileOne);
    vi.spyOn(profileApi, 'getProficiency').mockResolvedValue(emptyProficiency);
    vi.spyOn(profileApi, 'getCvText').mockImplementation((id) =>
      id === cvOneId ? Promise.resolve(firstCvText) : secondText.promise,
    );
    vi.spyOn(profileApi, 'selectCv').mockResolvedValue(profileTwo);
    const { result } = renderHook(() => useProficiency('docling'));
    await waitFor(() => expect(result.current.cvText).toEqual(firstCvText));

    let selection!: Promise<void>;
    await act(async () => {
      selection = result.current.selectCv(cvTwoId);
      await waitFor(() => expect(profileApi.getCvText).toHaveBeenCalledWith(cvTwoId, expect.any(AbortSignal)));
    });
    expect(result.current.profile?.active_cv_id).toBe(cvTwoId);
    expect(result.current.cvText).toBeNull();

    await act(async () => {
      secondText.resolve({
        id: cvTwoId,
        original_name: 'Second.pdf',
        parser: 'docling',
        parser_version: '2.55.1',
        text: 'Second CV text.',
      });
      await selection;
    });
    expect(result.current.cvText?.id).toBe(cvTwoId);
  });

  test('keeps optimistic revision conflicts visible and preserves proficiency state', async () => {
    vi.spyOn(profileApi, 'getProfile').mockResolvedValue(emptyProfile);
    vi.spyOn(profileApi, 'getProficiency').mockResolvedValue(populatedProficiency);
    vi.spyOn(profileApi, 'saveProficiencyBatch').mockRejectedValue(
      new Error('My proficiency changed; reload it before saving this update.'),
    );
    const { result } = renderHook(() => useProficiency('docling'));
    await waitFor(() => expect(result.current.proficiency).toEqual(populatedProficiency));
    const draft: ProficiencyDraft = {
      id: manualId,
      concept: 'Python',
      comfort: 'comfortable',
      note: 'Pending edit.',
      kind: 'manual',
    };

    await act(async () => {
      await expect(result.current.saveProficiency([draft])).rejects.toThrow(/changed; reload/i);
    });
    expect(result.current.proficiencyError).toMatch(/changed; reload/i);
    expect(result.current.proficiency).toEqual(populatedProficiency);
  });

  test('refreshes the latest proficiency after model requirement registration and ignores an aborted stale response', async () => {
    vi.spyOn(profileApi, 'getProfile').mockResolvedValue(emptyProfile);
    const initialLoad = deferred<ProficiencyState>();
    const olderRefresh = deferred<ProficiencyState>();
    const newerRefresh = deferred<ProficiencyState>();
    const getState = vi
      .spyOn(profileApi, 'getProficiency')
      .mockReturnValueOnce(initialLoad.promise)
      .mockReturnValueOnce(olderRefresh.promise)
      .mockReturnValueOnce(newerRefresh.promise);
    const { result } = renderHook(() => useProficiency('docling'));
    await act(async () => initialLoad.resolve(emptyProficiency));

    let refreshOne!: Promise<void>;
    let refreshTwo!: Promise<void>;
    await act(async () => {
      refreshOne = result.current.refreshProficiency();
      refreshTwo = result.current.refreshProficiency();
    });
    expect(getState.mock.calls[1]?.[0]?.aborted).toBe(true);

    const latest: ProficiencyState = {
      schema_version: 1,
      revision: 6,
      entries: [populatedProficiency.entries[1]],
    };
    await act(async () => newerRefresh.resolve(latest));
    await act(async () => olderRefresh.reject(new DOMException('Request aborted.', 'AbortError')));
    await Promise.all([refreshOne, refreshTwo]);

    expect(result.current.proficiency).toEqual(latest);
    expect(getState).toHaveBeenCalledTimes(3);
  });
});
