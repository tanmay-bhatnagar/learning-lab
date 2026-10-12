import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getCvText,
  getProfile,
  getProficiency,
  parseProfileParser,
  revokeCv as revokeCvRequest,
  saveProficiencyBatch,
  selectCv as selectCvRequest,
  uploadCv as uploadCvRequest,
  type CvText,
  type Profile,
  type ProficiencyBatchInput,
  type ProficiencyEntry,
  type ProficiencyState,
} from '../api/profile';
import type { ComfortLevel, ProficiencyDraft } from '../domain/proficiency';

type UseProficiencyResult = {
  profile: Profile | null;
  proficiency: ProficiencyState | null;
  cvText: CvText | null;
  profileError: string | null;
  proficiencyError: string | null;
  cvError: string | null;
  refreshProficiency: () => Promise<void>;
  uploadCv: (file: File, originalName: string) => Promise<void>;
  selectCv: (cvId: string) => Promise<void>;
  revokeCv: (cvId: string) => Promise<void>;
  saveProficiency: (drafts: ProficiencyDraft[]) => Promise<void>;
};

const errorMessage = (error: unknown, fallback: string): string => (error instanceof Error ? error.message : fallback);

function buildBatch(
  current: ProficiencyState,
  drafts: ProficiencyDraft[],
): Omit<ProficiencyBatchInput, 'expected_revision'> {
  const additions: ProficiencyBatchInput['additions'] = [];
  const updates: ProficiencyBatchInput['updates'] = [];
  const byId = new Map(current.entries.map((entry) => [entry.id, entry]));
  const requirementIds = new Set<string>();

  for (const draft of drafts) {
    const concept = draft.concept.trim();
    const notes = draft.note;
    if (!concept) throw new Error('Each proficiency topic needs a name.');

    if (draft.kind === 'manual') {
      const existing = byId.get(draft.id);
      if (!existing) {
        if (draft.comfort === '') throw new Error(`Choose a proficiency level for ${concept} before saving.`);
        additions.push({ concept, comfort: draft.comfort, notes });
        continue;
      }
      if (existing.source_kind !== 'user_manual') {
        throw new Error(`The saved row for ${concept} is not a manual proficiency entry.`);
      }
      const update: ProficiencyBatchInput['updates'][number] = { id: existing.id };
      update.concept = concept;
      if (draft.comfort !== existing.comfort) {
        if (draft.comfort === '') throw new Error(`Choose a proficiency level for ${concept} before saving.`);
        update.comfort = draft.comfort;
      }
      if (notes !== (existing.notes ?? '')) update.notes = notes;
      if (Object.keys(update).length > 1) updates.push(update);
      continue;
    }

    const requirementId = draft.requirementId;
    if (!requirementId) throw new Error(`The requirement identity for ${concept} is missing.`);
    if (requirementIds.has(requirementId)) throw new Error(`The requirement ${concept} appears more than once.`);
    requirementIds.add(requirementId);
    const matches = current.entries.filter(
      (entry): entry is Extract<ProficiencyEntry, { source_kind: 'model_requirement' }> =>
        entry.source_kind === 'model_requirement' && entry.requirement_id === requirementId,
    );
    if (matches.length !== 1) {
      throw new Error(`Could not identify exactly one saved requirement for ${concept}.`);
    }
    const existing = matches[0];
    if (draft.id !== existing.id && draft.id !== `requirement:${requirementId}`) {
      throw new Error(`The saved requirement identity for ${concept} changed. Reload My proficiency.`);
    }
    const update: ProficiencyBatchInput['updates'][number] = { id: existing.id };
    const comfort = draft.comfort === '' ? null : (draft.comfort as ComfortLevel);
    if (comfort !== existing.comfort) update.comfort = comfort;
    if (notes !== (existing.notes ?? '')) update.notes = notes;
    if (Object.keys(update).length > 1) updates.push(update);
  }
  return { additions, updates };
}

export function useProficiency(parser: string): UseProficiencyResult {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [proficiency, setProficiency] = useState<ProficiencyState | null>(null);
  const [cvText, setCvText] = useState<CvText | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [proficiencyError, setProficiencyError] = useState<string | null>(null);
  const [cvOperationError, setCvOperationError] = useState<string | null>(null);
  const [cvPreviewError, setCvPreviewError] = useState<string | null>(null);
  const profileRef = useRef<Profile | null>(null);
  const proficiencyRef = useRef<ProficiencyState | null>(null);
  const cvTextRef = useRef<CvText | null>(null);
  const mountedRef = useRef(false);
  const previewController = useRef<AbortController | null>(null);
  const profileLoadController = useRef<AbortController | null>(null);
  const proficiencyLoadController = useRef<AbortController | null>(null);
  const proficiencyRefreshController = useRef<AbortController | null>(null);
  const cvMutationController = useRef<AbortController | null>(null);
  const cvMutationRevision = useRef(0);
  const previewRevision = useRef(0);
  const savePending = useRef(false);

  const adoptProfile = useCallback((next: Profile) => {
    profileRef.current = next;
    setProfile(next);
  }, []);

  const adoptProficiency = useCallback((next: ProficiencyState) => {
    proficiencyRef.current = next;
    setProficiency(next);
  }, []);

  const adoptCvText = useCallback((next: CvText | null) => {
    cvTextRef.current = next;
    setCvText(next);
  }, []);

  const loadCvPreview = useCallback(
    async (cvId: string | null) => {
      previewController.current?.abort();
      const revision = ++previewRevision.current;
      if (!cvId) {
        if (mountedRef.current) adoptCvText(null);
        return;
      }
      if (cvTextRef.current?.id !== cvId && mountedRef.current) adoptCvText(null);
      const controller = new AbortController();
      previewController.current = controller;
      try {
        const text = await getCvText(cvId, controller.signal);
        if (mountedRef.current && revision === previewRevision.current && !controller.signal.aborted) {
          adoptCvText(text);
          setCvPreviewError(null);
        }
      } catch (error) {
        if (mountedRef.current && revision === previewRevision.current && !controller.signal.aborted) {
          adoptCvText(null);
          setCvPreviewError(errorMessage(error, 'Could not load the selected CV text.'));
        }
      }
    },
    [adoptCvText],
  );

  useEffect(() => {
    mountedRef.current = true;
    const profileController = new AbortController();
    const proficiencyController = new AbortController();
    profileLoadController.current = profileController;
    proficiencyLoadController.current = proficiencyController;
    getProfile(profileController.signal).then(
      (value) => {
        if (!mountedRef.current || profileController.signal.aborted) return;
        adoptProfile(value);
        setProfileError(null);
        void loadCvPreview(value.active_cv_id);
      },
      (error: unknown) => {
        if (mountedRef.current && !profileController.signal.aborted) {
          setProfileError(errorMessage(error, 'Could not load the shared CV profile.'));
        }
      },
    );
    getProficiency(proficiencyController.signal).then(
      (value) => {
        if (!mountedRef.current || proficiencyController.signal.aborted) return;
        adoptProficiency(value);
        setProficiencyError(null);
      },
      (error: unknown) => {
        if (mountedRef.current && !proficiencyController.signal.aborted) {
          setProficiencyError(errorMessage(error, 'Could not load My proficiency.'));
        }
      },
    );
    return () => {
      mountedRef.current = false;
      profileController.abort();
      proficiencyController.abort();
      proficiencyRefreshController.current?.abort();
      previewController.current?.abort();
      cvMutationController.current?.abort();
    };
  }, [adoptProfile, adoptProficiency, loadCvPreview]);

  const refreshProficiency = useCallback(async () => {
    proficiencyLoadController.current?.abort();
    proficiencyRefreshController.current?.abort();
    const controller = new AbortController();
    proficiencyRefreshController.current = controller;
    setProficiencyError(null);
    try {
      const latest = await getProficiency(controller.signal);
      if (mountedRef.current && !controller.signal.aborted && proficiencyRefreshController.current === controller) {
        adoptProficiency(latest);
      }
    } catch (error) {
      if (controller.signal.aborted || proficiencyRefreshController.current !== controller) return;
      if (mountedRef.current) setProficiencyError(errorMessage(error, 'Could not refresh My proficiency.'));
      throw error;
    } finally {
      if (proficiencyRefreshController.current === controller) proficiencyRefreshController.current = null;
    }
  }, [adoptProficiency]);

  const refreshProfile = useCallback(
    async (signal: AbortSignal) => {
      const next = await getProfile(signal);
      if (mountedRef.current && !signal.aborted) {
        adoptProfile(next);
        setProfileError(null);
        await loadCvPreview(next.active_cv_id);
      }
      return next;
    },
    [adoptProfile, loadCvPreview],
  );

  const uploadCv = useCallback(
    async (file: File, originalName: string) => {
      cvMutationController.current?.abort();
      const controller = new AbortController();
      cvMutationController.current = controller;
      const revision = ++cvMutationRevision.current;
      setCvOperationError(null);
      setCvPreviewError(null);
      try {
        const result = await uploadCvRequest(file, originalName, parseProfileParser(parser), controller.signal);
        if (!mountedRef.current || controller.signal.aborted || revision !== cvMutationRevision.current) return;
        if (result.status === 'error') {
          setCvOperationError(
            result.extraction_diagnostics.findings.join(' ') || 'The CV was saved, but text extraction failed.',
          );
        }
        await refreshProfile(controller.signal);
      } catch (error) {
        if (mountedRef.current && !controller.signal.aborted && revision === cvMutationRevision.current) {
          setCvOperationError(errorMessage(error, 'Could not upload the CV.'));
          throw error;
        }
      }
    },
    [parser, refreshProfile],
  );

  const selectCv = useCallback(
    async (cvId: string) => {
      const current = profileRef.current;
      if (!current) throw new Error('The shared CV profile has not loaded yet.');
      cvMutationController.current?.abort();
      previewController.current?.abort();
      const controller = new AbortController();
      cvMutationController.current = controller;
      const revision = ++cvMutationRevision.current;
      setCvOperationError(null);
      setCvPreviewError(null);
      try {
        const next = await selectCvRequest(cvId, current.revision, controller.signal);
        if (!mountedRef.current || controller.signal.aborted || revision !== cvMutationRevision.current) return;
        adoptProfile(next);
        setProfileError(null);
        await loadCvPreview(next.active_cv_id);
      } catch (error) {
        if (mountedRef.current && !controller.signal.aborted && revision === cvMutationRevision.current) {
          setCvOperationError(errorMessage(error, 'Could not select this CV.'));
        }
        throw error;
      }
    },
    [adoptProfile, loadCvPreview],
  );

  const revokeCv = useCallback(
    async (cvId: string) => {
      const current = profileRef.current;
      if (!current) throw new Error('The shared CV profile has not loaded yet.');
      cvMutationController.current?.abort();
      previewController.current?.abort();
      const controller = new AbortController();
      cvMutationController.current = controller;
      const revision = ++cvMutationRevision.current;
      setCvOperationError(null);
      setCvPreviewError(null);
      try {
        const next = await revokeCvRequest(cvId, current.revision, controller.signal);
        if (!mountedRef.current || controller.signal.aborted || revision !== cvMutationRevision.current) return;
        adoptProfile(next);
        setProfileError(null);
        await loadCvPreview(next.active_cv_id);
      } catch (error) {
        if (mountedRef.current && !controller.signal.aborted && revision === cvMutationRevision.current) {
          setCvOperationError(errorMessage(error, 'Could not revoke this CV.'));
        }
        throw error;
      }
    },
    [adoptProfile, loadCvPreview],
  );

  const saveProficiency = useCallback(
    async (drafts: ProficiencyDraft[]) => {
      const current = proficiencyRef.current;
      if (!current) throw new Error('My proficiency has not loaded yet.');
      if (savePending.current) throw new Error('A My proficiency save is already in progress.');
      let changes: Omit<ProficiencyBatchInput, 'expected_revision'>;
      try {
        changes = buildBatch(current, drafts);
      } catch (error) {
        const message = errorMessage(error, 'Could not prepare My proficiency changes.');
        if (mountedRef.current) setProficiencyError(message);
        throw error;
      }
      if (changes.additions.length === 0 && changes.updates.length === 0) {
        if (mountedRef.current) setProficiencyError(null);
        return;
      }
      savePending.current = true;
      setProficiencyError(null);
      try {
        const next = await saveProficiencyBatch({ expected_revision: current.revision, ...changes });
        if (mountedRef.current) {
          adoptProficiency(next);
          setProficiencyError(null);
        }
      } catch (error) {
        if (mountedRef.current) {
          setProficiencyError(errorMessage(error, 'Could not save My proficiency.'));
        }
        throw error;
      } finally {
        savePending.current = false;
      }
    },
    [adoptProficiency],
  );

  return {
    profile,
    proficiency,
    cvText,
    profileError,
    proficiencyError,
    cvError: cvOperationError ?? cvPreviewError,
    refreshProficiency,
    uploadCv,
    selectCv,
    revokeCv,
    saveProficiency,
  };
}
