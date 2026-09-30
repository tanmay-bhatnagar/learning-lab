import { vi } from 'vitest';
import type {
  Context,
  LabFile,
  Message,
  MessageRetrieval,
  Model,
  Settings,
  StreamEvent,
  Topic,
} from '../src/api/types';

export type StreamScript = (body: Record<string, unknown>, signal: AbortSignal) => AsyncIterable<StreamEvent>;

export type FakeApiOptions = {
  topics?: Topic[];
  messages?: Record<string, Message[]>;
  files?: Record<string, LabFile[]>;
  topicGoals?: Record<string, string>;
  settings?: Settings;
  models?: Model[];
  modelsError?: string;
  topicLoadDelayMs?: number;
  stream?: StreamScript;
  onSettingsPut?: (settings: Settings) => Settings | void;
  onLearningGoalPut?: (topic: string, goal: string) => void;
};

const defaultSettings: Settings = {
  model: 'qwen3.5:9b-q4_K_M',
  context_limit: 32768,
  parser: 'docling',
  embedding_model: 'nomic-embed-text',
  retrieval_top_k: 6,
};

const defaultModel: Model = {
  id: 'qwen3.5:9b-q4_K_M',
  name: 'qwen3.5:9b-q4_K_M',
  display_name: 'Qwen 3.5 · 9B',
  thinking: { type: 'toggle' },
};

const defaultTopics: Topic[] = [
  { id: 'topic-a', name: 'Topic A', learning_goal: 'Learn A' },
  { id: 'topic-b', name: 'Topic B', learning_goal: 'Learn B' },
];

const readyFile = (id: string, name: string): LabFile => ({
  id,
  name,
  status: 'ready',
  parser: 'docling',
  index_status: 'ready',
  index_mode: 'hybrid',
  page_count: 3,
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function* defaultStream(body: Record<string, unknown>, signal: AbortSignal): AsyncIterable<StreamEvent> {
  const message = String(body.message ?? '');
  yield { type: 'thinking', text: 'Considering…' };
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  yield { type: 'token', text: `Echo: ${message}` };
  yield {
    type: 'done',
    model: String(body.model ?? defaultSettings.model),
    context: { used: 100, limit: Number(body.context_limit ?? defaultSettings.context_limit) },
    retrieval: { mode: 'none', citations: [] },
  };
}

function parsePath(url: string): { pathname: string; search: string } {
  const parsed = new URL(url, 'http://test.local');
  return { pathname: parsed.pathname, search: parsed.search };
}

export function createFakeApi(options: FakeApiOptions = {}) {
  const topics = [...(options.topics ?? defaultTopics)];
  const messages: Record<string, Message[]> = { ...(options.messages ?? {}) };
  const files: Record<string, LabFile[]> = {
    'topic-a': [readyFile('file-1', 'paper-a.pdf')],
    'topic-b': [readyFile('file-2', 'paper-b.pdf')],
    ...(options.files ?? {}),
  };
  const topicGoals: Record<string, string> = {};
  for (const topic of topics) {
    topicGoals[topic.id] = topic.learning_goal ?? options.topicGoals?.[topic.id] ?? '';
  }
  Object.assign(topicGoals, options.topicGoals ?? {});
  let settings: Settings = { ...defaultSettings, ...options.settings };
  const models = options.models ?? [defaultModel];
  const modelsError = options.modelsError;
  let streamScript: StreamScript = options.stream ?? defaultStream;
  let onSettingsPut = options.onSettingsPut;
  let onLearningGoalPut = options.onLearningGoalPut;
  const topicLoadDelayMs = options.topicLoadDelayMs ?? 0;
  const delayTopicLoad = () =>
    topicLoadDelayMs > 0 ? new Promise((resolve) => setTimeout(resolve, topicLoadDelayMs)) : Promise.resolve();
  let pendingFilesPause: string | null = null;
  let filesGetRelease: (() => void) | null = null;
  let pendingGoalPause: string | null = null;
  let goalPutRelease: (() => void) | null = null;
  const markdownByFile: Record<string, string> = {
    'file-1': '# Paper A\n\nContent from A.',
    'file-2': '# Paper B\n\nContent from B.',
  };

  for (const topic of topics) {
    messages[topic.id] ??= [{ role: 'user', content: `Hello from ${topic.name}` }];
  }

  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const { pathname } = parsePath(url);
    const method = (init?.method ?? 'GET').toUpperCase();
    const apiPath = pathname.replace(/^\/api/, '') || '/';

    if (apiPath === '/topics' && method === 'GET') {
      return jsonResponse({ topics: topics.map(({ id, name }) => ({ id, name })) });
    }
    if (apiPath === '/topics' && method === 'POST') {
      const body = JSON.parse(String(init?.body ?? '{}')) as { name: string };
      const created = { id: `topic-${topics.length + 1}`, name: body.name };
      topics.push(created);
      messages[created.id] = [];
      files[created.id] = [];
      topicGoals[created.id] = '';
      return jsonResponse(created);
    }
    if (apiPath === '/models' && method === 'GET') {
      return jsonResponse({ models, ...(modelsError ? { error: modelsError } : {}) });
    }
    if (apiPath === '/settings' && method === 'GET') {
      return jsonResponse(settings);
    }
    if (apiPath === '/settings' && method === 'PUT') {
      const body = JSON.parse(String(init?.body ?? '{}')) as Settings;
      const saved = onSettingsPut?.(body) ?? body;
      settings = { ...settings, ...saved };
      return jsonResponse(settings);
    }

    const topicMatch = apiPath.match(/^\/topics\/([^/]+)(\/.*)?$/);
    if (!topicMatch) return jsonResponse({ detail: 'Not found' }, 404);
    const topicId = decodeURIComponent(topicMatch[1]);
    const rest = topicMatch[2] ?? '';

    if (rest === '' && method === 'GET') {
      await delayTopicLoad();
      const topic = topics.find((t) => t.id === topicId);
      if (!topic) return jsonResponse({ detail: 'Topic missing' }, 404);
      return jsonResponse({ ...topic, learning_goal: topicGoals[topicId] ?? '' });
    }
    if (rest === '/messages' && method === 'GET') {
      await delayTopicLoad();
      return jsonResponse({ messages: messages[topicId] ?? [], context: { used: 50, limit: settings.context_limit } });
    }
    if (rest === '/files' && method === 'GET') {
      await delayTopicLoad();
      if (pendingFilesPause === topicId) {
        pendingFilesPause = null;
        await new Promise<void>((resolve) => {
          filesGetRelease = resolve;
        });
      }
      return jsonResponse({ files: files[topicId] ?? [] });
    }
    if (rest === '/files' && method === 'POST') {
      const form = init?.body as FormData;
      const file = form.get('file') as File;
      const parser = String(form.get('parser') ?? 'docling');
      const record = readyFile(`file-${Date.now()}`, file.name);
      record.parser = parser;
      files[topicId] = [...(files[topicId] ?? []), record];
      markdownByFile[record.id] = `# ${file.name}\n\nUploaded content.`;
      return jsonResponse(record);
    }
    if (rest === '/learning-goal' && method === 'PUT') {
      if (pendingGoalPause === topicId) {
        pendingGoalPause = null;
        await new Promise<void>((resolve) => {
          goalPutRelease = resolve;
        });
      }
      const body = JSON.parse(String(init?.body ?? '{}')) as { learning_goal: string };
      topicGoals[topicId] = body.learning_goal;
      onLearningGoalPut?.(topicId, body.learning_goal);
      return jsonResponse({ learning_goal: body.learning_goal });
    }
    if (rest === '/chat' && method === 'POST') {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
      const signal = init?.signal ?? new AbortController().signal;
      const encoder = new TextEncoder();
      const streamBody = new ReadableStream({
        async start(controller) {
          try {
            for await (const event of streamScript(body, signal)) {
              if (signal.aborted) {
                controller.error(new DOMException('Aborted', 'AbortError'));
                return;
              }
              controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
              await new Promise((resolve) => setTimeout(resolve, 0));
            }
            controller.close();
          } catch (error) {
            controller.error(error);
          }
        },
      });
      return new Response(streamBody, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } });
    }

    const fileMatch = rest.match(/^\/files\/([^/]+)(\/.*)?$/);
    if (fileMatch) {
      const fileId = decodeURIComponent(fileMatch[1]);
      const fileRest = fileMatch[2] ?? '';
      if (fileRest === '/markdown' && method === 'GET') {
        return jsonResponse({ markdown: markdownByFile[fileId] ?? '# Empty\n' });
      }
    }

    return jsonResponse({ detail: `Unhandled ${method} ${apiPath}` }, 404);
  };

  return {
    fetch: fetchImpl,
    get settings() {
      return settings;
    },
    set settings(value: Settings) {
      settings = value;
    },
    get topics() {
      return topics;
    },
    get messages() {
      return messages;
    },
    get files() {
      return files;
    },
    get topicGoals() {
      return topicGoals;
    },
    setStream(script: StreamScript) {
      streamScript = script;
    },
    setOnSettingsPut(handler: (settings: Settings) => Settings | void) {
      onSettingsPut = handler;
    },
    setOnLearningGoalPut(handler: (topic: string, goal: string) => void) {
      onLearningGoalPut = handler;
    },
    setMarkdown(fileId: string, markdown: string) {
      markdownByFile[fileId] = markdown;
    },
    removeFile(topicId: string, fileId: string) {
      files[topicId] = (files[topicId] ?? []).filter((f) => f.id !== fileId);
    },
    pauseNextFilesGet(topicId: string) {
      pendingFilesPause = topicId;
    },
    releaseFilesGet() {
      filesGetRelease?.();
      filesGetRelease = null;
    },
    pauseNextGoalPut(topicId: string) {
      pendingGoalPause = topicId;
    },
    releaseGoalPut() {
      goalPutRelease?.();
      goalPutRelease = null;
    },
  };
}

export function installFakeApi(options?: FakeApiOptions) {
  const fake = createFakeApi(options);
  vi.stubGlobal('fetch', fake.fetch);
  return fake;
}

export function pdfFile(name: string, content = '%PDF-1.4 test'): File {
  return new File([content], name, { type: 'application/pdf' });
}

export type { MessageRetrieval, Context };
