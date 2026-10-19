import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { App } from '../src/App';
import { installFakeApi, pdfFile, type StreamScript } from './fakeApi';
import { MAX_PDF_BYTES } from '../src/uploads';
import type { Profile, ProfileCv, ProficiencyState } from '../src/api/profile';
import type { LearnerContext } from '../src/api/learnerContext';
import type { PrerequisiteState } from '../src/api/prerequisites';

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900, writable: true });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function waitForAppReady() {
  await waitFor(() => expect(screen.queryByText(/Connecting to your workspace/i)).not.toBeInTheDocument());
  await waitFor(() => expect(screen.getByRole('button', { name: 'Topic A' })).toBeInTheDocument());
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).not.toBeDisabled());
}

async function openFilesTab(user: ReturnType<typeof userEvent.setup>) {
  const tabs = document.querySelector('.tabs') as HTMLElement | null;
  if (!tabs) throw new Error('Workspace tabs missing');
  await user.click(within(tabs).getByRole('button', { name: /Attached files/i }));
  await waitFor(() => expect(screen.getByText(/Your reading material/i)).toBeInTheDocument());
}

async function openConversationTab(user: ReturnType<typeof userEvent.setup>) {
  const tabs = document.querySelector('.tabs') as HTMLElement | null;
  if (!tabs) throw new Error('Workspace tabs missing');
  await user.click(within(tabs).getByRole('button', { name: /Conversation/i }));
}

function fileInput() {
  return document.querySelector('input[type="file"]') as HTMLInputElement;
}

function asFileList(files: File[]): FileList {
  const list = {
    length: files.length,
    item: (index: number) => files[index] ?? null,
    *[Symbol.iterator]() {
      yield* files;
    },
  };
  files.forEach((file, index) => {
    Object.defineProperty(list, index, { value: file, enumerable: true });
  });
  return list as FileList;
}

function uploadThroughInput(files: File[]) {
  const input = fileInput();
  const list = asFileList(files);
  Object.defineProperty(input, 'files', { configurable: true, value: list });
  fireEvent.change(input, { target: { files: list } });
}

function installSharedProfileApi(
  options: {
    uploadStatus?: 'ready' | 'error';
    pauseProfileSave?: boolean;
    withReadyCv?: boolean;
    learnerIncludeCv?: boolean;
  } = {},
) {
  const base = installFakeApi();
  const baseFetch = base.fetch;
  const requests: Array<{ path: string; method: string; body?: unknown }> = [];
  let profile: Profile = { schema_version: 1, revision: 0, active_cv_id: null, cvs: [] };
  let proficiency: ProficiencyState = {
    schema_version: 1,
    revision: 3,
    entries: [
      {
        id: 'a'.repeat(32),
        concept: 'Python',
        comfort: 'refresher',
        notes: 'Synthetic manual entry.',
        source_kind: 'user_manual',
      },
      {
        id: 'b'.repeat(32),
        concept: 'Statistics',
        comfort: null,
        notes: '',
        source_kind: 'model_requirement',
        topic_id: 'synthetic-topic',
        assessment_id: 'synthetic-assessment',
        requirement_id: 'statistics',
      },
    ],
  };
  let uploadStatus = options.uploadStatus ?? 'ready';
  let pauseProfileSave = options.pauseProfileSave ?? false;
  let pauseCvUpload = false;
  let releaseProfileSave: (() => void) | null = null;
  let releaseCvUpload: (() => void) | null = null;
  const cvId = 'c'.repeat(32);
  if (options.withReadyCv) {
    profile = {
      schema_version: 1,
      revision: 1,
      active_cv_id: cvId,
      cvs: [
        {
          id: cvId,
          original_name: 'Synthetic CV.pdf',
          status: 'ready',
          revoked: false,
          parser: 'docling',
          parser_version: 'synthetic-parser',
          original_sha256: '1'.repeat(64),
          extracted_sha256: '2'.repeat(64),
          native_document_sha256: null,
          extraction_diagnostics: { status: 'ready', findings: [] },
          created_at: '2026-10-13T00:00:00Z',
        },
      ],
    };
  }
  const learnerPreferences = new Map<
    string,
    { schema_version: 1; revision: number; include_cv: boolean; active_assessment: null }
  >();

  const jsonResponse = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const failedCv = (originalName: string): ProfileCv => ({
    id: cvId,
    original_name: originalName,
    status: 'error',
    revoked: false,
    parser: 'docling',
    parser_version: 'synthetic-parser',
    original_sha256: '1'.repeat(64),
    extracted_sha256: null,
    native_document_sha256: null,
    extraction_diagnostics: { status: 'error', findings: ['No text was extracted.'] },
    created_at: '2026-10-13T00:00:00Z',
  });

  const fetchWithProfile = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const { pathname } = new URL(url, 'http://test.local');
    const method = (init?.method ?? 'GET').toUpperCase();
    const body = init?.body;
    const apiPath = pathname.replace(/^\/api/, '') || '/';
    const isLearnerContext = /^\/topics\/[^/]+\/conversations\/[^/]+\/learner-context$/.test(apiPath);
    if (!apiPath.startsWith('/profile') && !isLearnerContext) return baseFetch(input, init);
    const requestBody = body instanceof FormData ? body : typeof body === 'string' ? JSON.parse(body) : undefined;
    requests.push({ path: apiPath, method, body: requestBody });

    if (isLearnerContext) {
      const saved = learnerPreferences.get(apiPath) ?? {
        schema_version: 1 as const,
        revision: 0,
        include_cv: options.learnerIncludeCv ?? false,
        active_assessment: null,
      };
      if (method === 'GET') return jsonResponse(saved);
      if (method === 'PATCH') {
        const payload = requestBody as { expected_revision: number; include_cv: boolean };
        if (payload.expected_revision !== saved.revision) return jsonResponse({ detail: 'revision conflict' }, 409);
        const updated = { ...saved, revision: saved.revision + 1, include_cv: payload.include_cv };
        learnerPreferences.set(apiPath, updated);
        return jsonResponse(updated);
      }
    }

    if (apiPath === '/profile' && method === 'GET') return jsonResponse(profile);
    if (apiPath === '/profile/proficiency' && method === 'GET') return jsonResponse(proficiency);
    if (apiPath === '/profile/proficiency' && method === 'PUT') {
      if (pauseProfileSave) {
        pauseProfileSave = false;
        await new Promise<void>((resolve) => {
          releaseProfileSave = resolve;
        });
      }
      const payload = requestBody as {
        additions: Array<{ concept: string; comfort: 'comfortable' | 'refresher' | 'new' | 'unsure'; notes: string }>;
        updates: Array<{
          id: string;
          concept?: string;
          comfort?: 'comfortable' | 'refresher' | 'new' | 'unsure' | null;
          notes?: string;
        }>;
      };
      const additions = payload.additions.map((entry) => ({
        ...entry,
        id: 'd'.repeat(32),
        source_kind: 'user_manual' as const,
      }));
      proficiency = {
        ...proficiency,
        revision: proficiency.revision + 1,
        entries: [...proficiency.entries, ...additions],
      };
      return jsonResponse(proficiency);
    }
    if (apiPath === '/profile/cvs' && method === 'POST') {
      if (pauseCvUpload) {
        pauseCvUpload = false;
        await new Promise<void>((resolve) => {
          releaseCvUpload = resolve;
        });
      }
      const form = requestBody as FormData;
      const originalName = String(form.get('original_name'));
      const cv: ProfileCv =
        uploadStatus === 'error'
          ? failedCv(originalName)
          : {
              ...failedCv(originalName),
              status: 'ready',
              extracted_sha256: '2'.repeat(64),
              extraction_diagnostics: { status: 'ready', findings: [], note: 'Synthetic text extraction.' },
            };
      profile = { ...profile, revision: profile.revision + 1, cvs: [...profile.cvs, cv] };
      return jsonResponse({ ...cv, revision: profile.revision }, 201);
    }
    if (apiPath === `/profile/cvs/${cvId}/text` && method === 'GET') {
      return jsonResponse({
        id: cvId,
        original_name: profile.cvs[0]?.original_name ?? 'CV.pdf',
        parser: 'docling',
        parser_version: 'synthetic-parser',
        text: 'Synthetic full CV text.',
      });
    }
    if (apiPath === `/profile/cvs/${cvId}/select` && method === 'POST') {
      profile = { ...profile, revision: profile.revision + 1, active_cv_id: cvId };
      return jsonResponse(profile);
    }
    if (apiPath === `/profile/cvs/${cvId}/revoke` && method === 'POST') {
      profile = {
        ...profile,
        revision: profile.revision + 1,
        active_cv_id: null,
        cvs: profile.cvs.map((cv) => ({ ...cv, revoked: true })),
      };
      return jsonResponse(profile);
    }
    return jsonResponse({ detail: `Unhandled profile route ${method} ${apiPath}` }, 404);
  };
  vi.stubGlobal('fetch', fetchWithProfile);

  return {
    requests,
    setUploadStatus(status: 'ready' | 'error') {
      uploadStatus = status;
    },
    pauseNextProfileSave() {
      pauseProfileSave = true;
    },
    releaseProfileSave() {
      releaseProfileSave?.();
      releaseProfileSave = null;
    },
    pauseNextCvUpload() {
      pauseCvUpload = true;
    },
    releaseCvUpload() {
      const release = releaseCvUpload;
      releaseCvUpload = null;
      release?.();
    },
  };
}

describe('App characterization', () => {
  test('loads the active conversation assessment in My proficiency after reload without opening Map or requiring a CV', async () => {
    installSharedProfileApi();
    const activeAssessment = {
      file_id: 'file-a',
      assessment_id: 'assessment-a',
      map_revision: 'a'.repeat(64),
      section_id: 'section-a',
      goal: 'Understand this section',
    };
    const savedAssessment: PrerequisiteState['assessments'][number] = {
      attempt_id: 'attempt-a',
      assessment_id: activeAssessment.assessment_id,
      topic_id: 'topic-a',
      file_id: activeAssessment.file_id,
      map_revision: activeAssessment.map_revision,
      section_id: activeAssessment.section_id,
      cv_id: 'c'.repeat(32),
      cv_text_sha256: 'b'.repeat(64),
      source_sha256: 'd'.repeat(64),
      overview: 'Review the core ideas before continuing.',
      requirements: [
        {
          requirement_id: `req-${'e'.repeat(24)}`,
          concept: 'Basic Python',
          reason: 'The saved section uses short programs.',
          question: 'Are you already comfortable with Basic Python?',
          source_labels: ['S1'],
          cv_background: 'not_stated',
          cv_source_labels: [],
          cv_quote: '',
          comfort: null,
          comfort_status: 'pending',
        },
      ],
      sources: [{ label: 'S1', unit_id: 'unit-a', source_refs: ['doc:section-a'], pages: [1] }],
      finished_at: '2026-10-13T10:01:00Z',
    };
    const focusState: PrerequisiteState = {
      schema_version: 1,
      topic_id: 'topic-a',
      file_id: 'file-a',
      map_revision: null,
      selected_cv: null,
      attempts: [
        {
          id: savedAssessment.attempt_id,
          assessment_id: savedAssessment.assessment_id,
          topic_id: savedAssessment.topic_id,
          file_id: savedAssessment.file_id,
          map_revision: savedAssessment.map_revision,
          section_id: savedAssessment.section_id,
          status: 'completed',
          started_at: '2026-10-13T10:00:00Z',
          finished_at: savedAssessment.finished_at,
          provenance: {
            prompt_version: 'section-prerequisites-v2',
            source_sha256: savedAssessment.source_sha256,
            runtime_policy_sha256: 'f'.repeat(64),
            cv_id: savedAssessment.cv_id,
            cv_text_sha256: savedAssessment.cv_text_sha256,
            goal: activeAssessment.goal,
            model: 'local-model',
          },
          diagnostic: null,
        },
      ],
      assessments: [savedAssessment],
      current_assessment: null,
    };
    const requirementRow = {
      id: '9'.repeat(32),
      concept: 'Basic Python',
      comfort: null,
      notes: '',
      source_kind: 'model_requirement',
      topic_id: 'topic-a',
      assessment_id: 'assessment-a',
      requirement_id: `req-${'e'.repeat(24)}`,
    };
    const baseFetch = globalThis.fetch;
    let answerSaveBody: unknown;
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const pathname = new URL(url, 'http://test.local').pathname;
      if (pathname === '/api/profile') {
        return new Response(JSON.stringify({ detail: 'Synthetic CV integrity failed.' }), { status: 500 });
      }
      if (pathname === '/api/topics/topic-a/conversations/default/learner-context') {
        return new Response(
          JSON.stringify({ schema_version: 1, revision: 0, include_cv: false, active_assessment: activeAssessment }),
          { headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (pathname === '/api/topics/topic-a/files/file-a/prerequisites') {
        expect(new URL(url, 'http://test.local').searchParams.get('assessment_id')).toBe(
          activeAssessment.assessment_id,
        );
        return new Response(JSON.stringify(focusState), { headers: { 'Content-Type': 'application/json' } });
      }
      if (pathname === '/api/profile/proficiency' && (init?.method ?? 'GET') === 'GET') {
        const response = await baseFetch(input, init);
        const profileState = (await response.json()) as ProficiencyState;
        return new Response(JSON.stringify({ ...profileState, entries: [...profileState.entries, requirementRow] }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (pathname === '/api/profile/proficiency' && init?.method === 'PUT') {
        answerSaveBody = JSON.parse(String(init.body));
      }
      return baseFetch(input, init);
    });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await user.click(screen.getByRole('button', { name: 'My proficiency' }));

    expect(await screen.findByRole('combobox', { name: 'Your comfort with Basic Python' })).toBeInTheDocument();
    expect(screen.getByText(/Saved section assessment/)).toBeInTheDocument();
    expect(screen.queryByText(/Select a ready CV/i)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole('combobox', { name: 'Your comfort with Basic Python' }), 'unsure');
    await user.click(
      within(screen.getByRole('region', { name: 'Requirement answers' })).getByRole('button', {
        name: 'Save proficiency',
      }),
    );
    await waitFor(() => expect(screen.getByText('Your answers were saved to My proficiency.')).toBeInTheDocument());
    expect(answerSaveBody).toMatchObject({
      updates: [{ id: requirementRow.id, comfort: 'unsure' }],
      additions: [],
    });
  });

  test('explicitly imports the completed assessment and separately drafts follow-up without sending or replacing input', async () => {
    installSharedProfileApi({ withReadyCv: true });
    const baseFetch = globalThis.fetch;
    const revision = 'a'.repeat(64);
    const cvId = 'c'.repeat(32);
    const finishedAt = '2026-10-13T10:01:00Z';
    const assessment: PrerequisiteState['assessments'][number] = {
      attempt_id: 'attempt-a',
      assessment_id: 'assessment-a',
      topic_id: 'topic-a',
      file_id: 'file-1',
      map_revision: revision,
      section_id: 'section-a',
      cv_id: cvId,
      cv_text_sha256: '2'.repeat(64),
      source_sha256: 'd'.repeat(64),
      overview: 'Review these core ideas.',
      requirements: [],
      sources: [{ label: 'S1', unit_id: 'unit-a', source_refs: ['doc:section-a'], pages: [1] }],
      finished_at: finishedAt,
    };
    const attempt: PrerequisiteState['attempts'][number] = {
      id: 'attempt-a',
      assessment_id: assessment.assessment_id,
      topic_id: 'topic-a',
      file_id: 'file-1',
      map_revision: revision,
      section_id: 'section-a',
      status: 'completed',
      started_at: '2026-10-13T10:00:00Z',
      finished_at: finishedAt,
      provenance: {
        prompt_version: 'section-prerequisites-v2',
        source_sha256: assessment.source_sha256,
        runtime_policy_sha256: 'f'.repeat(64),
        cv_id: cvId,
        cv_text_sha256: assessment.cv_text_sha256,
        goal: 'Understand this section.',
        model: 'local-model',
      },
      diagnostic: null,
    };
    const prerequisiteState: PrerequisiteState = {
      schema_version: 1,
      topic_id: 'topic-a',
      file_id: 'file-1',
      map_revision: revision,
      selected_cv: { id: cvId, original_name: 'Synthetic CV.pdf', extracted_sha256: assessment.cv_text_sha256 },
      attempts: [attempt],
      assessments: [assessment],
      current_assessment: assessment,
    };
    let preference: LearnerContext = { schema_version: 1, revision: 0, include_cv: false, active_assessment: null };
    let messages: Array<{ role: string; content: string; prerequisite_import?: unknown }> = [
      { role: 'user', content: 'Hello from Topic A' },
    ];
    const importBodies: unknown[] = [];
    let chatRequests = 0;
    const focus = {
      file_id: 'file-1',
      assessment_id: assessment.assessment_id,
      map_revision: revision,
      section_id: 'section-a',
      goal: attempt.provenance.goal,
    };
    const importMetadata = {
      schema_version: 1,
      import_id: 'e'.repeat(64),
      conversation_id: 'default',
      topic_id: 'topic-a',
      file_id: 'file-1',
      assessment_id: assessment.assessment_id,
      map_revision: revision,
      section_id: 'section-a',
      section_title: 'Synthetic section',
      goal: attempt.provenance.goal,
      model: 'local-model',
      assessment_finished_at: finishedAt,
      imported_at: '2026-10-13T10:02:00Z',
      sources: assessment.sources,
      content_sha256: 'f'.repeat(64),
    };
    const importedMessage = {
      role: 'user',
      content: 'Saved prerequisite snapshot for Synthetic section.',
      prerequisite_import: importMetadata,
    };
    const map = {
      schema_version: 1,
      builder_version: 'synthetic',
      file_id: 'file-1',
      revision,
      source_revision: { pdf_sha256: 'b'.repeat(64), docling_sha256: 'c'.repeat(64) },
      outline_mode: 'headings',
      sections: [
        {
          id: 'section-a',
          source_ref: 'doc:section-a',
          title: 'Synthetic section',
          level: 1,
          pages: [1],
          text: 'Synthetic source text.',
          direct_unit_ids: [],
          source_unit_ids: [],
          children: [],
        },
      ],
      units: [],
      coverage: {
        total_units: 0,
        included_units: 0,
        excluded_units: 0,
        accounted_units: 0,
        total_source_items: 0,
        accounted_source_items: 0,
      },
      warnings: [],
      history: [],
    };
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const parsed = new URL(url, 'http://test.local');
      if (parsed.pathname === '/api/topics/topic-a/files' && init?.method === undefined) {
        const response = await baseFetch(input, init);
        const payload = (await response.json()) as { files: Array<Record<string, unknown>> };
        return new Response(
          JSON.stringify({ files: payload.files.map((file) => ({ ...file, docling_name: 'paper-a.docling.json' })) }),
          { headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (parsed.pathname === '/api/topics/topic-a/conversations/default/learner-context') {
        return new Response(JSON.stringify(preference), { headers: { 'Content-Type': 'application/json' } });
      }
      if (parsed.pathname === '/api/topics/topic-a/files/file-1/map') {
        return new Response(JSON.stringify({ status: 'ready', map }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (parsed.pathname === '/api/topics/topic-a/files/file-1/prerequisites') {
        return new Response(JSON.stringify(prerequisiteState), { headers: { 'Content-Type': 'application/json' } });
      }
      if (parsed.pathname === '/api/topics/topic-a/conversations/default/messages') {
        return new Response(JSON.stringify({ messages, context: { used: 0, limit: 32768 } }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (
        parsed.pathname === '/api/topics/topic-a/conversations/default/prerequisite-imports' &&
        init?.method === 'POST'
      ) {
        importBodies.push(JSON.parse(String(init.body)));
        const importedBefore = messages.some((message) => message.prerequisite_import);
        if (!importedBefore) {
          preference = { ...preference, revision: preference.revision + 1, active_assessment: focus };
          messages = [...messages, importedMessage];
        }
        return new Response(
          JSON.stringify({
            conversation_id: 'default',
            imported: !importedBefore,
            message: importedMessage,
            messages,
            learner_context: preference,
            context: { used: 20, limit: 32768 },
          }),
          { headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (parsed.pathname === '/api/topics/topic-a/conversations/default/chat' && init?.method === 'POST')
        chatRequests += 1;
      return baseFetch(input, init);
    });

    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    const composer = screen.getByRole('textbox', { name: 'Message' });
    await user.type(composer, 'Keep this existing thought');
    await user.click(screen.getByRole('button', { name: /Map/i }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'PDF for map' }), 'file-1');
    await user.click(await screen.findByRole('button', { name: 'Select section' }));

    await user.click(screen.getByRole('button', { name: 'Draft a follow-up' }));
    const composerAfterDraft = screen.getByRole('textbox', { name: 'Message' });
    expect(composerAfterDraft).toHaveValue(
      'Keep this existing thought\n\nI want to understand the concepts needed for “Synthetic section” in paper-a.pdf. Can you help me explore them using the documents I have selected?',
    );
    expect(chatRequests).toBe(0);

    await user.click(screen.getByRole('button', { name: /Map/i }));
    await user.click(screen.getByRole('button', { name: 'Add to “Main chat”' }));

    await waitFor(() => expect(screen.getByText(/Added to “Main chat”/)).toBeInTheDocument());
    expect(importBodies[0]).toEqual({
      file_id: 'file-1',
      assessment_id: assessment.assessment_id,
      revision,
      section_id: 'section-a',
      expected_revision: 0,
    });
    const tabs = document.querySelector('.tabs');
    expect(tabs).not.toBeNull();
    await user.click(within(tabs as HTMLElement).getByRole('button', { name: /Conversation/i }));
    expect(await screen.findByText('Saved prerequisite snapshot for Synthetic section.')).toBeInTheDocument();
    const draftedInput =
      'Keep this existing thought\n\nI want to understand the concepts needed for “Synthetic section” in paper-a.pdf. Can you help me explore them using the documents I have selected?';
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue(draftedInput);

    await user.click(screen.getByRole('button', { name: /Map/i }));
    const retryImportButton = screen.getByRole('button', { name: 'Add to “Main chat”' });
    await waitFor(() => expect(retryImportButton).toBeEnabled());
    await user.click(retryImportButton);
    expect(await screen.findByText(/Already in “Main chat”/)).toBeInTheDocument();
    expect(importBodies[1]).toEqual({
      file_id: 'file-1',
      assessment_id: assessment.assessment_id,
      revision,
      section_id: 'section-a',
      expected_revision: 1,
    });
    await user.click(within(tabs as HTMLElement).getByRole('button', { name: /Conversation/i }));
    expect(await screen.findByText('Saved prerequisite snapshot for Synthetic section.')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue(draftedInput);
    expect(chatRequests).toBe(0);
  });

  test('opens My proficiency without a topic, saves a manual skill, and reloads authoritative state', async () => {
    const profileApi = installSharedProfileApi();
    const user = userEvent.setup();
    const view = render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'My proficiency' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'My proficiency' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'My proficiency' })).toBeInTheDocument());

    const manualSection = screen.getByRole('region', { name: 'Your skills and concepts' });
    expect(within(manualSection).getByRole('group', { name: 'Python' })).toBeInTheDocument();
    expect(within(manualSection).queryByText('Statistics')).not.toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: 'Add a skill or concept' }), 'Probability');
    await user.click(screen.getByRole('button', { name: 'Add skill' }));
    const probability = screen.getByRole('group', { name: 'Probability' });
    await user.selectOptions(within(probability).getByLabelText('Your comfort with Probability'), 'refresher');
    await user.click(screen.getByRole('button', { name: 'Save proficiency' }));
    await waitFor(() => expect(screen.getByRole('group', { name: 'Probability' })).toBeInTheDocument());
    expect(
      profileApi.requests.find((request) => request.path === '/profile/proficiency' && request.method === 'PUT'),
    ).toMatchObject({
      body: {
        expected_revision: 3,
        additions: [{ concept: 'Probability', comfort: 'refresher', notes: '' }],
        updates: [{ id: 'a'.repeat(32), concept: 'Python' }],
      },
    });

    view.unmount();
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'My proficiency' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'My proficiency' }));
    await waitFor(() => expect(screen.getByRole('group', { name: 'Probability' })).toBeInTheDocument());
    expect(
      profileApi.requests.filter((request) => request.path === '/profile/proficiency' && request.method === 'GET'),
    ).toHaveLength(2);
  });

  test('closes the mobile sidebar when opening My proficiency', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390, writable: true });
    installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'My proficiency' })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Show sidebar' }));
    expect(document.querySelector('.app')).not.toHaveClass('collapsed');

    await user.click(screen.getByRole('button', { name: 'My proficiency' }));

    expect(document.querySelector('.app')).toHaveClass('collapsed');
  });

  test('reads and revision-saves the selected conversation CV preference without refetching CV text', async () => {
    const profileApi = installSharedProfileApi({ withReadyCv: true });
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'My proficiency' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'My proficiency' }));
    const preference = screen.getByRole('checkbox', { name: 'Always include CV in Main chat' });
    expect(screen.getByText('Always include CV in “Main chat”')).toBeInTheDocument();
    await waitFor(() => expect(preference).toBeEnabled());
    expect(preference).not.toBeChecked();
    const cvTextReads = profileApi.requests.filter((request) => request.path.endsWith('/text')).length;

    await user.click(preference);

    await waitFor(() => expect(preference).toBeChecked());
    expect(
      profileApi.requests.find(
        (request) =>
          request.path === '/topics/topic-a/conversations/default/learner-context' && request.method === 'PATCH',
      ),
    ).toMatchObject({ body: { expected_revision: 0, include_cv: true } });
    expect(profileApi.requests.filter((request) => request.path.endsWith('/text'))).toHaveLength(cvTextReads);
    expect(profileApi.requests.some((request) => request.path.endsWith('/chat'))).toBe(false);
  });

  test('lets the user turn off a saved CV preference after revoking the CV', async () => {
    const profileApi = installSharedProfileApi({ withReadyCv: true, learnerIncludeCv: true });
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'My proficiency' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'My proficiency' }));
    const preference = screen.getByRole('checkbox', { name: 'Always include CV in Main chat' });
    await waitFor(() => expect(preference).toBeChecked());

    await user.click(screen.getByRole('button', { name: 'Stop future use' }));
    await waitFor(() => expect(preference).toBeChecked());
    expect(preference).toBeEnabled();
    await user.click(preference);

    await waitFor(() => expect(preference).not.toBeChecked());
    expect(
      profileApi.requests.find(
        (request) =>
          request.path === '/topics/topic-a/conversations/default/learner-context' && request.method === 'PATCH',
      ),
    ).toMatchObject({ body: { expected_revision: 0, include_cv: false } });
  });

  test('uploads the exact renamed shared CV and leaves extraction failures visible and unselectable', async () => {
    const profileApi = installSharedProfileApi({ uploadStatus: 'error' });
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'My proficiency' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'My proficiency' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'My proficiency' })).toBeInTheDocument());

    const file = pdfFile('original-resume.pdf');
    fireEvent.change(screen.getByLabelText('Upload your CV'), { target: { files: [file] } });
    const filename = screen.getByRole('textbox', { name: 'CV filename' });
    await user.clear(filename);
    await user.type(filename, 'Research Profile.pdf');
    await user.click(screen.getByRole('button', { name: 'Upload CV' }));

    await waitFor(() => expect(screen.getAllByText(/No text was extracted/).length).toBeGreaterThan(0));
    const upload = profileApi.requests.find((request) => request.path === '/profile/cvs' && request.method === 'POST');
    expect((upload?.body as FormData).get('original_name')).toBe('Research Profile.pdf');
    expect((upload?.body as FormData).get('file')).toMatchObject({ name: file.name, type: file.type, size: file.size });
    expect(screen.getByRole('button', { name: 'Research Profile.pdf' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Download original CV' })).toHaveAttribute(
      'href',
      `/api/profile/cvs/${'c'.repeat(32)}/original`,
    );
    expect(screen.getByText(/select an active CV with complete extracted text/i)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Always include CV in Main chat' })).toBeDisabled();
  });

  test('a shared proficiency save blocks chat, PDF upload, and settings saves through activity', async () => {
    const profileApi = installSharedProfileApi({ pauseProfileSave: true });
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'My proficiency' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'My proficiency' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'My proficiency' })).toBeInTheDocument());

    await user.type(screen.getByRole('textbox', { name: 'Add a skill or concept' }), 'Probability');
    await user.click(screen.getByRole('button', { name: 'Add skill' }));
    await user.selectOptions(screen.getByLabelText('Your comfort with Probability'), 'new');
    await user.click(screen.getByRole('button', { name: 'Save proficiency' }));
    await waitFor(() =>
      expect(
        profileApi.requests.some((request) => request.path === '/profile/proficiency' && request.method === 'PUT'),
      ).toBe(true),
    );

    try {
      await user.click(screen.getByRole('button', { name: 'Conversations' }));
      expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Add PDF' })).toBeDisabled();
      await user.click(screen.getByRole('button', { name: 'Settings' }));
      expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled();
    } finally {
      profileApi.releaseProfileSave();
    }
  });

  test('a shared CV upload blocks other activities until conversion finishes', async () => {
    const profileApi = installSharedProfileApi();
    profileApi.pauseNextCvUpload();
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'My proficiency' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'My proficiency' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'My proficiency' })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Upload your CV'), { target: { files: [pdfFile('resume.pdf')] } });
    await user.click(screen.getByRole('button', { name: 'Upload CV' }));
    await waitFor(() =>
      expect(profileApi.requests.some((request) => request.path === '/profile/cvs' && request.method === 'POST')).toBe(
        true,
      ),
    );

    try {
      await user.click(screen.getByRole('button', { name: 'Conversations' }));
      expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Add PDF' })).toBeDisabled();
      await user.click(screen.getByRole('button', { name: 'Settings' }));
      expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled();
    } finally {
      profileApi.releaseCvUpload();
    }
  });

  test('preflight chat rejection preserves the draft and removes the optimistic turn', async () => {
    installFakeApi({ chatStatus: 422 });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    const composer = screen.getByRole('textbox', { name: 'Message' });
    await user.type(composer, 'A prompt that does not fit');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/Prompt does not fit/i));
    expect(composer).toHaveValue('A prompt that does not fit');
    expect(document.querySelector('.message-list')).not.toHaveTextContent('A prompt that does not fit');
  });

  test('extra document search is opt-in for a selected ready indexed document and resets after acceptance', async () => {
    const requests: Array<Record<string, unknown>> = [];
    const stream: StreamScript = async function* (body) {
      requests.push(body);
      yield { type: 'token', text: 'Grounded response.' };
      yield { type: 'done', model: 'qwen3.5:9b-q4_K_M', context: { used: 10, limit: 32768 } };
    };
    installFakeApi({ stream });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    expect(screen.getByRole('checkbox', { name: 'Allow extra search' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Allow extra search' })).toBeDisabled();
    expect(screen.getByText(/select.*ready.*indexed document/i)).toBeInTheDocument();

    await openFilesTab(user);
    await user.click(screen.getByRole('checkbox', { name: 'Include paper-a.pdf in chat' }));
    await openConversationTab(user);
    const extraSearch = screen.getByRole('checkbox', { name: 'Allow extra search' });
    expect(extraSearch).toBeEnabled();
    await user.click(extraSearch);
    expect(extraSearch).toBeChecked();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Can you search further?');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => expect(screen.getByText('Grounded response.')).toBeInTheDocument());
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({ extra_search: true });
    await waitFor(() => expect(extraSearch).not.toBeChecked());
  });

  test('changing selection so no indexed document remains clears the opt-in', async () => {
    installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await openFilesTab(user);
    const file = screen.getByRole('checkbox', { name: 'Include paper-a.pdf in chat' });
    await user.click(file);
    await openConversationTab(user);
    const extraSearch = screen.getByRole('checkbox', { name: 'Allow extra search' });
    await user.click(extraSearch);
    expect(extraSearch).toBeChecked();

    await openFilesTab(user);
    await user.click(screen.getByRole('checkbox', { name: 'Include paper-a.pdf in chat' }));
    await openConversationTab(user);
    const resetExtraSearch = screen.getByRole('checkbox', { name: 'Allow extra search' });
    expect(resetExtraSearch).not.toBeChecked();
    expect(resetExtraSearch).toBeDisabled();
  });

  test('changing topic immediately hides the prior conversation opt-in', async () => {
    installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await openFilesTab(user);
    await user.click(screen.getByRole('checkbox', { name: 'Include paper-a.pdf in chat' }));
    await openConversationTab(user);
    await user.click(screen.getByRole('checkbox', { name: 'Allow extra search' }));
    expect(screen.getByRole('checkbox', { name: 'Allow extra search' })).toBeChecked();

    await user.click(screen.getByRole('button', { name: 'Topic B' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Topic B' })).toBeInTheDocument());
    const newTopicExtraSearch = screen.getByRole('checkbox', { name: 'Allow extra search' });
    expect(newTopicExtraSearch).not.toBeChecked();
    expect(newTopicExtraSearch).toBeDisabled();
  });

  test('preflight rejection preserves both the message draft and the opt-in choice', async () => {
    installFakeApi({ chatStatus: 422 });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await openFilesTab(user);
    await user.click(screen.getByRole('checkbox', { name: 'Include paper-a.pdf in chat' }));
    await openConversationTab(user);
    const extraSearch = screen.getByRole('checkbox', { name: 'Allow extra search' });
    await user.click(extraSearch);
    const composer = screen.getByRole('textbox', { name: 'Message' });
    await user.type(composer, 'Keep the opt-in on if preflight rejects.');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/Prompt does not fit/i));
    expect(composer).toHaveValue('Keep the opt-in on if preflight rejects.');
    expect(extraSearch).toBeChecked();
  });

  test('older model refresh response cannot replace the latest completed model list', async () => {
    const fake = installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await user.click(screen.getByRole('button', { name: /Settings/i }));
    fake.pauseNextModelsGet();
    await user.click(screen.getByRole('button', { name: 'Refresh available models' }));
    fake.setModels([{ id: 'new-model', name: 'new-model', display_name: 'New model', thinking: { type: 'none' } }]);
    await user.click(screen.getByRole('button', { name: 'Refresh available models' }));
    await waitFor(() => expect(screen.getByRole('option', { name: 'New model' })).toBeInTheDocument());
    fake.releaseModelsGet();
    await waitFor(() => expect(screen.getByRole('option', { name: 'New model' })).toBeInTheDocument());
    expect(screen.getByRole('option', { name: /Qwen 3\.5 · 9B.*unavailable/ })).toBeInTheDocument();
  });

  test('topic switch resets messages, files, selection, goal and input; goal save blocked until ready', async () => {
    installFakeApi({
      messages: {
        'topic-a': [{ role: 'user', content: 'Message A' }],
        'topic-b': [{ role: 'user', content: 'Message B' }],
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    expect(screen.getByText('Message A')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Learn A')).toBeInTheDocument();

    const goalField = screen.getByPlaceholderText(/What would you like to learn/i);
    await user.clear(goalField);
    await user.type(goalField, 'Draft goal not saved');

    await user.click(screen.getByRole('button', { name: 'Topic B' }));
    await waitFor(() => expect(screen.getByText('Message B')).toBeInTheDocument());
    expect(screen.queryByText('Message A')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('Learn B')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Draft goal not saved')).not.toBeInTheDocument();

    await user.clear(screen.getByPlaceholderText(/What would you like to learn/i));
    await user.type(screen.getByPlaceholderText(/What would you like to learn/i), 'New goal');
    await user.click(screen.getByRole('button', { name: /Save learning goal/i }));
    await waitFor(() => expect(screen.getByText(/Learning goal saved/i)).toBeInTheDocument());
  });

  test('uses the saved session goal when opening a section in the map', async () => {
    const fake = installFakeApi({
      files: {
        'topic-a': [
          {
            id: 'file-1',
            name: 'paper-a.pdf',
            status: 'ready',
            parser: 'docling',
            docling_name: 'paper-a.docling.json',
            index_status: 'ready',
            index_mode: 'hybrid',
            page_count: 1,
            asset_count: 0,
            assets: [],
            warnings: [],
          },
        ],
      },
    });
    const baseFetch = fake.fetch;
    const mapRequests: string[] = [];
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url, 'http://test.local').pathname.includes('/map')) mapRequests.push(url);
      if (new URL(url, 'http://test.local').pathname === '/api/topics/topic-a/files/file-1/map') {
        return new Response(
          JSON.stringify({
            status: 'ready',
            map: {
              schema_version: 1,
              builder_version: 'synthetic',
              file_id: 'file-1',
              revision: 'a'.repeat(64),
              source_revision: { pdf_sha256: 'b'.repeat(64), docling_sha256: 'c'.repeat(64) },
              outline_mode: 'headings',
              sections: [
                {
                  id: 'section-a',
                  source_ref: 'doc:section-a',
                  title: 'Synthetic section',
                  level: 1,
                  pages: [1],
                  text: 'Synthetic source text.',
                  direct_unit_ids: [],
                  source_unit_ids: [],
                  children: [],
                },
              ],
              units: [],
              coverage: {
                total_units: 0,
                included_units: 0,
                excluded_units: 0,
                accounted_units: 0,
                total_source_items: 0,
                accounted_source_items: 0,
              },
              warnings: [],
              history: [],
            },
          }),
          { headers: { 'Content-Type': 'application/json' } },
        );
      }
      return baseFetch(input, init);
    });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await user.clear(screen.getByPlaceholderText(/What would you like to learn/i));
    await user.type(screen.getByPlaceholderText(/What would you like to learn/i), 'Saved goal for the section');
    await user.click(screen.getByRole('button', { name: /Save learning goal/i }));
    await waitFor(() => expect(screen.getByText(/Learning goal saved/i)).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /Map/i }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'PDF for map' }), 'file-1');
    await waitFor(() => expect(mapRequests.length).toBeGreaterThan(0));
    await user.click(await screen.findByRole('button', { name: 'Select section' }));

    expect(await screen.findByRole('textbox', { name: 'What do you want from this section?' })).toHaveValue(
      'Saved goal for the section',
    );
  });

  test('send streams thinking and token events; stop aborts with partial text', async () => {
    const slowStream: StreamScript = async function* (_body, signal) {
      yield { type: 'thinking', text: 'Hmm' };
      await new Promise((resolve) => setTimeout(resolve, 30));
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      yield { type: 'token', text: 'Partial' };
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, 2000);
        signal.addEventListener('abort', () => {
          clearTimeout(timer);
          resolve(undefined);
        });
      });
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      yield { type: 'token', text: ' answer' };
      yield { type: 'done', model: 'qwen3.5:9b-q4_K_M', context: { used: 10, limit: 32768 } };
    };
    installFakeApi({ stream: slowStream });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Hello stream');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => expect(screen.getByText(/Hmm/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('Partial')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Stop response' }));

    await waitFor(() => expect(screen.getByText(/Response stopped/i)).toBeInTheDocument());
    expect(screen.getByText('Partial')).toBeInTheDocument();
    expect(screen.queryByText(/Partial answer/)).not.toBeInTheDocument();
    expect(screen.getByText(/Response incomplete/i)).toBeInTheDocument();
  });

  test('stream error marks assistant message incomplete', async () => {
    const errorStream: StreamScript = async function* () {
      yield { type: 'token', text: 'Started' };
      yield { type: 'error', message: 'Model unavailable' };
    };
    installFakeApi({ stream: errorStream });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Fail please');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    await waitFor(() => expect(screen.getByText(/Model unavailable/i)).toBeInTheDocument());
    expect(screen.getByText(/Response incomplete/i)).toBeInTheDocument();
    expect(screen.getByText('Started')).toBeInTheDocument();
  });

  test('upload rejects non-PDF and oversize files', async () => {
    installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await openFilesTab(user);

    const zone = screen.getByRole('button', { name: /Drop PDFs here/i });
    fireEvent.drop(zone, {
      dataTransfer: { files: asFileList([new File(['hello'], 'notes.txt', { type: 'text/plain' })]), types: ['Files'] },
    });
    await waitFor(() => expect(screen.getAllByText(/not a PDF/i).length).toBeGreaterThan(0));

    const big = pdfFile('big.pdf', '%PDF-' + 'x'.repeat(MAX_PDF_BYTES));
    fireEvent.drop(zone, { dataTransfer: { files: asFileList([big]), types: ['Files'] } });
    await waitFor(() => expect(screen.getAllByText(/25 MiB/i).length).toBeGreaterThan(0));
  });

  test('upload blocked while chat is sending', async () => {
    const slowStream: StreamScript = async function* () {
      yield { type: 'thinking', text: '…' };
      await new Promise((resolve) => setTimeout(resolve, 500));
      yield { type: 'done', context: { used: 1, limit: 32768 } };
    };
    installFakeApi({ stream: slowStream });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'busy');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('button', { name: 'Stop response' });
    await openFilesTab(user);
    uploadThroughInput([pdfFile('blocked.pdf')]);
    await waitFor(() => expect(screen.getByText(/Finish the current action/i)).toBeInTheDocument());
  });

  test('drag-and-drop shows feedback and accepts PDFs', async () => {
    installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await openFilesTab(user);

    const zone = screen.getByRole('button', { name: /Drop PDFs here/i });
    fireEvent.dragEnter(zone, { dataTransfer: { types: ['Files'], dropEffect: 'copy' } });
    expect(screen.getByText(/Release to add your PDFs/i)).toBeInTheDocument();

    fireEvent.drop(zone, {
      dataTransfer: { files: [pdfFile('dropped.pdf')], types: ['Files'] },
    });
    await waitFor(() => expect(screen.getByText('dropped.pdf')).toBeInTheDocument());
  });

  test('model select reports server mismatch', async () => {
    const altModel = {
      id: 'llama3:8b',
      name: 'llama3:8b',
      display_name: 'Llama 3 · 8B',
      thinking: { type: 'none' as const },
    };
    const qwen = { id: 'qwen3.5:9b-q4_K_M', name: 'qwen3.5:9b-q4_K_M', thinking: { type: 'toggle' as const } };
    const fake = installFakeApi({ models: [altModel, qwen] });
    fake.setOnSettingsPut((next) => ({ ...next, model: qwen.id }));
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.click(screen.getByRole('button', { name: /Settings/i }));
    await user.selectOptions(screen.getByLabelText(/Default model/i), 'llama3:8b');
    await waitFor(() => expect(screen.getByText(/server did not apply the selected model/i)).toBeInTheDocument());
  });

  test('model select persists when server accepts', async () => {
    const altModel = {
      id: 'llama3:8b',
      name: 'llama3:8b',
      display_name: 'Llama 3 · 8B',
      thinking: { type: 'none' as const },
    };
    const qwen = { id: 'qwen3.5:9b-q4_K_M', name: 'qwen3.5:9b-q4_K_M', thinking: { type: 'toggle' as const } };
    const fake = installFakeApi({ models: [altModel, qwen] });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.click(screen.getByRole('button', { name: /Settings/i }));
    await user.selectOptions(screen.getByLabelText(/Default model/i), 'llama3:8b');
    await waitFor(() => expect(screen.getByText(/Llama 3 · 8B selected/i)).toBeInTheDocument());
    expect(fake.settings.model).toBe('llama3:8b');
  });

  test('settings save persists draft values', async () => {
    const fake = installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.click(screen.getByRole('button', { name: /Settings/i }));
    const contextInput = screen.getByLabelText(/Context limit/i);
    await user.clear(contextInput);
    await user.type(contextInput, '4096');
    await user.click(screen.getByRole('button', { name: /Save settings/i }));
    await waitFor(() => expect(screen.getByText(/Settings saved/i)).toBeInTheDocument());
    expect(fake.settings.context_limit).toBe(4096);
  });

  test('file preview loads markdown and switches to original tab', async () => {
    const fake = installFakeApi();
    fake.setMarkdown('file-1', '# Preview markdown\n\nBody text.');
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await openFilesTab(user);

    await user.click(screen.getByRole('button', { name: /Inspect/i }));
    await waitFor(() => expect(screen.getByText('Preview markdown')).toBeInTheDocument());
    expect(screen.getByText(/Body text/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Original PDF' }));
    expect(screen.getByTitle(/Original PDF: paper-a.pdf/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close preview' }));
    expect(screen.queryByText('Preview markdown')).not.toBeInTheDocument();
  });

  test('Refresh files re-fetches the file list without clearing conversation or input', async () => {
    const fake = installFakeApi({
      messages: { 'topic-a': [{ role: 'user', content: 'Keep this?' }] },
      files: {
        'topic-a': [
          {
            id: 'file-1',
            name: 'paper-a.pdf',
            status: 'ready',
            parser: 'docling',
            index_status: 'ready',
            index_mode: 'hybrid',
          },
          {
            id: 'file-2',
            name: 'paper-aux.pdf',
            status: 'ready',
            parser: 'docling',
            index_status: 'ready',
            index_mode: 'hybrid',
          },
        ],
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).not.toBeDisabled());
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'typed before refresh');

    await openFilesTab(user);
    const checkboxA = screen.getByRole('checkbox', { name: /paper-a.pdf/i });
    const checkboxB = screen.getByRole('checkbox', { name: /paper-aux.pdf/i });
    await user.click(checkboxA);
    await user.click(checkboxB);
    expect(checkboxA).toBeChecked();
    expect(checkboxB).toBeChecked();

    fake.removeFile('topic-a', 'file-1');
    await user.click(screen.getByRole('button', { name: 'Refresh files' }));
    await waitFor(() => expect(screen.queryByText('paper-a.pdf')).not.toBeInTheDocument());
    expect(screen.getByRole('checkbox', { name: /paper-aux.pdf/i })).toBeChecked();

    const tabs = document.querySelector('.tabs') as HTMLElement | null;
    if (!tabs) throw new Error('Workspace tabs missing');
    await user.click(within(tabs).getByRole('button', { name: /Conversation/i }));
    expect(screen.getByText('Keep this?')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('typed before refresh');
    expect(screen.queryByRole('checkbox', { name: /paper-a.pdf/i })).not.toBeInTheDocument();
  });

  test('shows thinking preference storage errors', async () => {
    installFakeApi();
    const original = window.localStorage.setItem.bind(window.localStorage);
    const setItem = vi.spyOn(window.localStorage, 'setItem').mockImplementation((key, value) => {
      if (key === 'lab-thinking') throw new Error('quota');
      original(key, value);
    });
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Thinking preferences could not be saved/i)).toBeInTheDocument());
    setItem.mockRestore();
  });

  test('creates a topic while a chat reply is streaming without stale stream writes', async () => {
    const fake = installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();

    await user.click(screen.getByRole('button', { name: 'Create topic' }));
    await user.type(screen.getByPlaceholderText(/Understanding neural networks/i), 'Stream topic');

    fake.pauseNextChatStream();
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Hello while modal open');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('button', { name: 'Stop response' });

    const dialog = screen.getByRole('dialog', { name: /Make room for a new topic/i });
    await user.click(within(dialog).getByRole('button', { name: /^Create topic$/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Stream topic' })).toBeInTheDocument());
    expect(fake.topicPostCount).toBe(1);

    fake.releaseChatStream();
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Stop response' })).not.toBeInTheDocument(), {
      timeout: 3000,
    });

    expect(screen.queryByText(/Echo:/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Hello while modal open')).not.toBeInTheDocument();
  });

  test('Refresh files ignores stale response after topic switch', async () => {
    const fake = installFakeApi({
      files: {
        'topic-a': [{ id: 'file-1', name: 'paper-a.pdf', status: 'ready', parser: 'docling' }],
        'topic-b': [{ id: 'file-2', name: 'paper-b.pdf', status: 'ready', parser: 'docling' }],
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await openFilesTab(user);
    fake.pauseNextFilesGet('topic-a');
    void user.click(screen.getByRole('button', { name: 'Refresh files' }));
    await user.click(screen.getByRole('button', { name: 'Topic B' }));
    await waitFor(() => expect(screen.getByText('paper-b.pdf')).toBeInTheDocument());
    fake.releaseFilesGet();
    await waitFor(() => expect(screen.getByText('paper-b.pdf')).toBeInTheDocument());
    expect(screen.queryByText('paper-a.pdf')).not.toBeInTheDocument();
  });

  test('Refresh files cannot overwrite an upload completed while the refresh is pending', async () => {
    const fake = installFakeApi();
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await openFilesTab(user);
    fake.pauseNextFilesGet('topic-a');
    await user.click(screen.getByRole('button', { name: 'Refresh files' }));
    uploadThroughInput([pdfFile('new-upload.pdf')]);
    await waitFor(() => expect(screen.getByText('new-upload.pdf')).toBeInTheDocument());
    fake.releaseFilesGet();
    await waitFor(() => expect(screen.getByText('new-upload.pdf')).toBeInTheDocument());
  });

  test('legacy rendered-image count does not block citations to later physical pages', async () => {
    installFakeApi({
      files: {
        'topic-a': [{ id: 'legacy', name: 'legacy.pdf', status: 'ready', parser: 'markitdown', page_count: 1 }],
      },
      messages: {
        'topic-a': [
          {
            role: 'assistant',
            content: 'See page four.',
            retrieval: {
              mode: 'keyword',
              citations: [
                {
                  chunk_id: 'legacy:0',
                  file_id: 'legacy',
                  file_name: 'legacy.pdf',
                  headings: [],
                  pages: [4],
                  bboxes: [],
                  assets: [],
                  trace: {},
                  text: 'Evidence on page four.',
                },
              ],
            },
          },
        ],
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await waitForAppReady();
    await user.click(screen.getByRole('button', { name: /Sources/i }));
    expect(screen.getByRole('link', { name: 'Page 4' })).toHaveAttribute(
      'href',
      '/api/topics/topic-a/files/legacy/original#page=4',
    );
  });
});
