# Architecture conformance review — 1 October 2026

Scope: the whole Code repository at `dev` `fa52c07` (clean tree), measured against [engineering conventions](../../docs/engineering.md), the contracts in [architecture](../../docs/architecture.md), and the [review checklist](../../.agents/skills/review/references/checklist.md). Procedure: the research skill (trace code, cite evidence, separate confirmed facts from unverified concerns), with implementation slices in the design-skill format. Read-only: no application code was changed. Every source, test, script, CI and agent-configuration file was read.

## 1. Verdict

**Moderate-to-structural refactoring, concentrated in two hotspots. No rewrite is needed.**

- **Structural:** `apps/web/src/main.tsx` (one component holding the whole browser application) and `services/api/lab/main.py` (one 375-line `create_app` closure holding every route, the upload pipeline, prompt assembly and chat streaming).
- **Moderate, cross-cutting:** typed persisted records, an error taxonomy that is independent of HTTP, explicit configuration, and removal of test-only branches from production code.
- **Local:** most other modules. `context.py`, `index.py` ranking helpers, `docling_pipeline.py`, `retrievalTrace.tsx` and the frontend helper modules are already close to the target and are good templates.
- **Enforcement gap:** the conventions are almost entirely enforced by review. For high-trust agents with humans out of the loop, the rules must become checks, or the hotspots will regrow. `engineering.md` also has no frontend conventions at all, which is how `main.tsx` reached its current shape.

Three confirmed defects and one plausible one surfaced. Fix them separately, before the refactor, so the refactor stays behavior-preserving (section 3).

Refactor levels used below: **none**; **local** (edits inside one module; no interface change); **moderate** (module interface or contract changes, callers updated); **structural** (module split or ownership change).

## 2. What is already right — preserve it

- `context.py`: a pure function over a deep copy, a documented contract, thorough tests. This is the model for business decisions.
- `storage.py`: path and symlink checks, `O_NOFOLLOW` reads, atomic `write_json` and `write_bytes` with fsync, and corrupt-data errors that are visible rather than overwritten.
- `index.py`: `_fuse_ranked_hits`, `_cosine` and `_fts_query` are pure and deterministic; the schema is versioned with a migration.
- `docling_pipeline.py`: frozen dataclasses, an explicit `ParseArtifacts` boundary, and actionable error messages.
- Explicit degradation: retrieval and tokenizer fallbacks return labelled warnings instead of silently succeeding (with one hole; see finding D1).
- The frontend helper modules (`modelControls.ts`, `uploads.ts`, `citationsHelpers.ts`, `retrievalTraceHelpers.ts`) are pure and tested. `retrievalTrace.tsx` shows the target component style: formatted, small subcomponents, logic in helpers.
- Tests use synthetic fixtures and isolated roots. CI runs lint, tests, the build and an isolated real-HTTP upload.

## 3. Defects to fix before refactoring

These change behavior, so each needs its own commit and regression test. Do not fold them into refactor commits.

**Status on 1 October 2026: D1–D5 are fixed, each with a regression test, and the documentation drift (P1-f) is corrected. Phase 1 is complete.** The rows below keep the original findings as the baseline. The fixes are:

- **D1.** `lab.contracts.EmbeddingUnavailable` is raised for a missing, remote or unreachable model; uploads fall back to a keyword index and searches to keyword retrieval. Rejected document embeddings still fail indexing, while a rejected query falls back to keywords. Verified live against local Ollama with an uninstalled embedding model. The same review found that `scripts/chunking_demo.py` called `embed_texts` without its required lock; that is fixed too.
- **D2.** The topic effect resets the goal state, and `learningGoal.canSaveLearningGoal` requires a loaded, idle topic.
- **D3.** `storage.write_new_bytes` writes the original PDF and legacy Markdown durably with exclusive create (fsync, then a hard link).
- **D4.** `file_records.mark_interrupted` runs when the file list is read, according to decision 3.
- **D5.** Confirmed by reproduction. With the HTTP middleware, the lock was released only when the cyclic garbage collector ran; without it, the lock was never released. `FinalizedStreamingResponse` now runs chat cleanup exactly once in every disconnect case.

| ID | Severity | Status | Finding |
| --- | --- | --- | --- |
| D1 | High | **Confirmed by execution** | When Ollama is running but the embedding model is not pulled (the default `nomic-embed-text`), `models.embed_texts` raises `ValueError("Requested model is not installed locally")` (`models.py:170-171`). `retrieval.index_chunks` and `retrieval.search` catch only `httpx.HTTPError` (`retrieval.py:50`, `retrieval.py:79`). Consequences: an upload gets no keyword index at all (`main.py:228-233` marks `index_status: error`). Chat then falls back to attaching the file's whole Markdown (`main.py:344-346`), and the chat response does not say so; only the file list shows a warning. For a file indexed earlier, chat and trace fail with HTTP 500. This breaks the handoff invariant "keyword retrieval still works when embeddings are unavailable". It is a **regression from the 30 September refactor**: `b2a6b71` caught `Exception`, and `bcfe2a9` narrowed the catch without classifying this expected outage. No test covers it. Reproduced in an isolated temporary store: both functions raise `ValueError`. |
| D2 | Medium | Confirmed by reading | Topic-switch state is incomplete in `main.tsx`. The topic effect (`main.tsx:64`) does not reset `learningGoal`, `goalDraft` or `goalNotice`. If a topic load fails, the goal editor still shows the previous topic's goal. `saveLearningGoal` (`main.tsx:82`) does not check `topicReady`, so an edited stale goal can be written to the new topic. "Learning goal saved" also persists across topic switches. |
| D3 | Medium | Confirmed by reading | The original PDF — the most important artifact — is written with plain `open("xb")` (`main.py:201-202`), with no fsync or temp-and-rename. The helper `storage.write_bytes` is atomic but uses `os.replace`, which would allow overwriting. A crash mid-write leaves a truncated original, and its record is already persisted as `processing` (`main.py:200-205`). |
| D4 | Medium | Confirmed by reading | Records written as `status: processing` (`main.py:200-205`) have no recovery path. If the process dies during parsing, the record stays `processing` forever and the UI can never select it (`main.tsx:156`, via the status regex). `engineering.md` requires documented recovery for partial writes. This needs a design decision: for example, mark stale `processing` records as `error: interrupted` on read or at startup. |
| D5 | High if real | **Unverified** | The chat route acquires the topic lock (`main.py:331-334`) and releases it only inside the streaming generator's `finally` (`main.py:455-466`). If the client disconnects before Starlette starts iterating the generator, `finally` never runs, because closing a never-started async generator does not execute its body. The topic would then return 409 "busy" until the API restarts. Starlette 1.6.0's `StreamingResponse.__call__` can cancel `stream_response` before the first `__anext__`. Assign this to the **debug** role for reproduction before changing it. The structural fix is in slice BE-4. |

## 4. Frontend (`apps/web`)

### 4.1 `main.tsx` — structural

**Size and shape.** The file has 166 lines and 37 KB. The JSX occupies 15 physical lines totalling 20.5 KB. Line 156 is 5,339 characters and line 154 (the entire settings page) is 4,908. 32 lines exceed 200 characters. One `App` component contains all state and behavior.

**Agent-editing cost, measured.** Commit `fa52c07` added about 2.4 KB of new content to `main.tsx` but produced 11.8 KB of diff churn, because each change rewrites a multi-kilobyte line. Diffs are close to unreviewable, and string-replacement edits need huge unique anchors. This is the main agent-friendliness blocker in the repository.

**State inventory** (43 `useState`, 8 `useRef`, 5 `useEffect`):

| Concern | State (line) | Refs |
| --- | --- | --- |
| Navigation and chrome | `page`, `tab`, `sidebar` (27); `newTopic`, `creating` (31) | `bottom` (37) |
| Topics and bootstrap | `topics`, `topic` (25); `loading` (30) | `topicRef` (37) |
| Models, settings and thinking | `models`, `settings`, `draft` (26); `saving`, `notice` (30-31); `parser` (32); `thinking` (33); `switching`, `selectionStatus`, `selectionError` (35); `modelError` (31) | `persistenceLock` (34) |
| Topic session | `messages`, `files`, `selected`, `context` (28); `topicLoading`, `topicReady` (30); `revision` (62) | — |
| Learning goal | `learningGoal`, `goalDraft`, `goalSaving`, `goalNotice` (29) | — |
| Chat streaming | `sending`, `input` (30-31); `follow` (76) | `streamController` (37) |
| Upload and drag-drop | `uploading` (30); `dragging`, `dropBlocked`, `dropFeedback` (36) | `uploadLock`, `dragDepth`, `dropFeedbackTimer`, `uploadInput` (34-37) |
| Preview | `preview`, `previewTab`, `markdown`, `previewLoading`, `previewError` (32) | — |
| Errors | `error` (31), shared by six unrelated operations | — |

**Effects and I/O.** Effects: bootstrap (61), topic load (63-69), preview load (70-75), autoscroll (77), window drag guards (140-147). Async handlers: `refreshModels` (45), `initialize` (46-60), `createTopic` (80), `saveLearningGoal` (81-87), `send` (88-101), `upload` (102-117), `persistSettings` (118-134). Twelve API endpoints are called directly from the component. `localStorage` is read at 33 and written at 78, and `window` is accessed at 27, 42-43, 145-146 and 151.

**Convention violations:**

| Severity | Location | Finding |
| --- | --- | --- |
| High | 38, 89, 104, 119 | **Implicit state machine.** "An operation is in progress" is spread over four booleans (`sending`, `uploading`, `saving`, `goalSaving`) and three refs (`streamController`, `persistenceLock`, `uploadLock`). Each handler re-derives its own guard from a different subset. Transitions are scattered `setX` calls. D2 is a direct symptom. The convention asks for deliberate state transitions. |
| High | 91-99 | **Business decisions inside effectful handlers.** Stream-event folding into messages (append the placeholder, patch the last message, set model and retrieval, mark incomplete) is inline and untested. It should be a pure `applyStreamEvent(messages, event)`. |
| High | 150-163 | All JSX is in one render: the settings page, files page, chat, composer, two modals and the sidebar. `thinkingControl` (149) is a component disguised as a closure. |
| Medium | 78 | A side effect (`localStorage.setItem`) runs inside a `setState` updater. Updaters must be pure, and React may invoke them twice. The `catch {}` swallows the error. |
| Medium | 33 | The `localStorage` value goes through `JSON.parse` with no validation and is trusted as `Record<string, boolean \| string>`. This is an unvalidated boundary. |
| Medium | 56 | The settings-migration PUT uses `.catch(() => {})`: a silent failure that bypasses `persistenceLock`, so it can race a user save. |
| Medium | 156 | Business rules in JSX: file selectability via `/failed\|error\|pending\|.../i.test(file.status)`, the extraction-diagnostic label, and the "unassessed" legacy rule. `LabFile.status` is `string`, not a union (`api.ts:6`). |
| Medium | 64, 156 | The topic-reset list is hand-maintained (D2). "Refresh files" (156) bumps `revision`, which also clears the chat input, the selection and the messages. That may be unintended; it is unverified. |
| Low | 73, 163 | URLs are built inline, duplicating `filePath` and `originalPdfUrl` in `api.ts`. |
| Low | 166 | Rendering at import time means `App` cannot be imported by a test. |
| Low | 15, 157 | The parser list and starter prompts are parallel arrays joined by index. The parser union is duplicated in the backend (`main.py:76`, `main.py:184`). |

**Target decomposition** (behavior-preserving):

```text
src/main.tsx                 createRoot only
src/App.tsx                  composition: hooks + page components
src/state/activity.ts        pure: Activity = idle | sending | uploading | savingSettings | savingGoal | creatingTopic; canStart(activity, op)
src/state/topicSession.ts    pure reducer: topicRequested | topicLoaded | topicFailed | goalSaved | fileUploaded | selectionToggled ...
src/state/chatStream.ts      pure: startTurn(messages, text), applyStreamEvent(messages, event), failTurn(messages, aborted)
src/domain/files.ts          pure: isSelectable, fileMeta, diagnosticLabel (typed status unions)
src/domain/contextMeter.ts   pure: meter(context, settings)
src/api/client.ts            api(), stream(), one error-detail parser, runtime validation of responses
src/api/urls.ts              every URL builder (absorbs assetApiUrl, originalPdfUrl, inline URLs)
src/api/types.ts             wire types (moved from api.ts)
src/hooks/useBootstrap.ts    topics, models, settings, migration (reports failures)
src/hooks/useTopicSession.ts load and abort per topic, dispatches the reducer
src/hooks/useChat.ts         stream lifecycle and AbortController
src/hooks/useUploads.ts      validation, sequential upload, drag-drop state
src/hooks/useSettings.ts     persistSettings, selectModel, draft
src/hooks/useThinkingPrefs.ts validated localStorage boundary
src/hooks/useFilePreview.ts
src/components/…             Sidebar, TopBar, ErrorBanner, SettingsPage (+3 cards), WorkspaceTabs,
                             FilesPanel/FileRow/UploadZone, ChatPanel/GoalEditor/MessageList/Composer/ContextMeter,
                             NewTopicModal, PreviewModal, RichText, VisualAssets (shared)
```

No state library is warranted: `useReducer` plus pure modules covers it.

### 4.2 Other frontend files

| File | Level | Findings |
| --- | --- | --- |
| `api.ts` | Moderate | `response.json() as Promise<T>` (77) and `JSON.parse(line) as StreamEvent` (92) are unchecked casts at the external boundary; `engineering.md` requires validation there. Error-detail parsing differs between `api()` (74, which stringifies non-string detail such as FastAPI 422 arrays) and `stream()` (89, which drops it). `fileAssetPath` (84) is unused and duplicated by `assetApiUrl`. `Message.role` is `string`. It mixes wire types, transport and URL builders. |
| `citations.tsx` | Local | `CitationAssets` (8-34) duplicates `AssetThumbnails` in `retrievalTrace.tsx:32-58` line for line. The page-link decisions (38-48: dedupe, validate, range check) are untested inline logic. It has a duplicate `./api` import (3, 6) and non-null assertions after `hasSources` (60-73) instead of narrowing. |
| `citationsHelpers.ts` | Local | `citationLocation` (24) is used only by a test. `modeBadgeLabel` duplicates `modeLabel` in `retrievalTraceHelpers.ts:51` with a different default ("No retrieval" versus "No matches"). |
| `retrievalTrace.tsx` | Local | The target style. There is no abort on unmount, unlike `main.tsx`; the error text duplicates `errorText`; `key={name}` (169) collides for identically named files. |
| `retrievalTraceHelpers.ts` | Local | Pure and tested. `assetApiUrl` should move to the URL module. |
| `modelControls.ts` | Local | `modelContextMax(_model)` (13) and `validateContext(value, _model)` (51) carry speculative unused parameters. `modelContextMax` is used only by tests. It also owns settings normalization and chat-request shaping, so its cohesion is mixed. `validateContext` fails `noImplicitReturns` (TS7030). |
| `uploads.ts` | None | Pure decisions plus one file-read boundary. |
| `styles.css` | Local (mechanical) | 23 KB in 9 lines, with line 1 at 13,606 characters. Reformat with no rule changes. |

### 4.3 Frontend tests and safety net

- Four test files, 18 tests, all on helper modules. **Nothing exercises `main.tsx`, `citations.tsx` or `retrievalTrace.tsx`.** A refactor of `main.tsx` currently has no safety net.
- The harness (`tests/*.mjs`) transpiles one module to a `data:` URL, so a module under test **cannot value-import another module**. This constraint silently forces duplication (for example, `assetApiUrl` versus `fileAssetPath`) and would block the decomposition above. The `load` helper is copy-pasted into all four files.
- The frontend has no formatter and no linter (no `react-hooks/exhaustive-deps`), so the current density is permitted.
- `apps/web/README.md:14` is stale. It says uploads use MarkItDown or AnyDoc, that AnyDoc is the default parser, and that a model's lower maximum context constrains validation. The code does none of these (`modelControls.ts:5-15`).

## 5. Backend (`services/api`)

### 5.1 Module scorecard

✓ conforms, ~ partial, ✗ violates.

| Module | Pure decisions / effects separated | Explicit dependencies | No global state | Caller inputs preserved | Narrow errors | Typed boundary | Cohesion | Level |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `main.py` | ✗ | ✗ | ~ | ~ | ✗ | ✗ | ✗ | **Structural** |
| `storage.py` | ✓ | ~ | ✓ | ✓ | ~ (HTTP errors) | ✗ | ~ | Moderate |
| `contracts.py` | — | — | ✓ | — | — | ~ | ✓ | Moderate (expand) |
| `parse_pipeline.py` | ~ | ✓ | ✓ | ✓ | ~ | ~ | ~ | Moderate |
| `docling_pipeline.py` | ✓ | ~ (env) | ✓ | ✓ | ~ | ~ | ✓ | Local |
| `chunking.py` | ✓ | ~ (test seam) | ✓ | ✓ | ✓ | ~ | ✓ | Local |
| `embedding_config.py` | ~ | ~ (env) | ~ (`lru_cache`) | ✓ | ~ | ~ | ~ | Local |
| `index.py` | ✓ | ✓ | ✓ | ✓ | ~ (`IndexError`) | ✗ (`dict[str, Any]`) | ✓ | Local-to-moderate |
| `retrieval.py` | ~ | ✓ | ✓ | ✓ | ✗ (D1) | ~ | ✓ | Moderate |
| `models.py` | ~ | ✗ (import-time env) | ✗ (`OLLAMA_URL`) | ✓ | ~ | ~ | ~ | Moderate |
| `context.py` | ✓ | ✓ | ✓ | ✓ | ✓ | ~ | ✓ | None |
| `parsers.py` | ✓ | ✓ | ✓ | ✓ | ~ | ✓ | ✓ | None |

Measured with Ruff probes beyond the current configuration (non-mutating):
- `create_app` has cyclomatic complexity 67 and 237 statements. `chat` is 22 and 105, `stream_chat` 23 and 63, and `parse_and_persist` 13 and 63.
- Eight blind `except Exception` handlers, six of them in `main.py`.
- 66 unannotated parameters and 19 untyped public returns in `lab/`.
- One builtin shadowed (`index.py:19`).

### 5.2 Findings

**`main.py` (structural)**

| Severity | Location | Finding |
| --- | --- | --- |
| High | 95-469 | `create_app` is a 375-line closure holding middleware, 21 route registrations, the per-topic lock map, backend selection, upload orchestration, prompt assembly and streaming persistence. Nothing inside it can be tested except through HTTP. |
| High | 121-131, 207, 424-431 | **Test-only branches in production code.** When `model_backend` is injected, embeddings bypass the generation lock (126-127) and `stream_chat` is called with a different signature: no `context_metadata`, no `generation_lock` (431). When `converter` is injected, the Docling path is skipped for every parser (207). So API tests never exercise the production call signature, the lock pass-through, or Docling dispatch. The fakes (`test_api.py:11-25`, `test_retrieval_api.py:11-22`) implement the old positional contract. |
| High | 381-408 | **Prompt assembly is a pure decision embedded in a route.** The order is system rules plus goal, then history, reversed evidence, attachments and the question. It also computes the atomic evidence indices and retained-citation filtering. This is the core invariant "citations agree with evidence sent", and it can only be tested end to end. It needs a pure `build_chat_prompt` returning a typed plan. The latest feature (392-396) extended the inline pattern. |
| High | 183-253 | **Upload is about 70 lines mixing everything:** filename validation, size and header checks, ID and clock generation (197-199, not injected), a non-atomic original write (D3), `processing` persistence (D4), parser dispatch, indexing, progressive in-place `record.update`/`setdefault().append` (16 mutation sites in this file), and error mapping. The file-record state machine (`processing` → `ready`/`error`, and `index_status` `ready`/`error`/`not_indexed`) is implicit. |
| Medium | 228, 248, 322, 376, 453 | Blind excepts. 228 turns programming errors in indexing into a warning. 248 turns them into "Conversion failed (TypeError)". 376 silently sets `vision = False`, an unreported degradation. |
| Medium | 98-103, 472 | Environment variables are read inside `create_app`. `app = create_app()` runs at import time, so importing `lab.main` builds an app bound to the **personal** `../Learning` root unless the environment is set first. `scripts/smoke.py:23-25` relies on setting `os.environ` before import. That is a latent hazard for the "never drive a personal topic" rule. |
| Medium | 209, 297, 310, 347 | `Settings(**read_json(store.settings, {}))` is repeated four times, and a corrupt settings file becomes a 500 error. |
| Medium | 151, 181 | API responses are the raw persisted `topic.json` and `files.json` records, so any storage change is an API change. Conversations (R1 item 4) will need that separation. |
| Medium | 329-467 | Manual lock acquire and release across a generator (D5). Session dictionaries are mutated in both the handler and the generator (409, 442-443, 463). |
| Low | 76/184, 56/68/188 | Duplicated parser literal and duplicated control-character validation. |

**Cross-cutting**

| Severity | Location | Finding |
| --- | --- | --- |
| High | `storage.py:8` and throughout | Storage raises `fastapi.HTTPException`. `parse_pipeline`, `index`, `retrieval` and the scripts inherit HTTP semantics. R1 item 7 (LangGraph tools) will call these functions outside HTTP. Replace with domain errors mapped in one exception handler. |
| High | `contracts.py` | The central record — the file record in `files.json`, which is the state machine — has no type. The same is true of topic, session, message and settings records. `extraction_diagnostics` is `dict[str, object]` (69), while the frontend declares a precise union (`api.ts:18`). `store` is untyped everywhere. |
| Medium | `models.py:11`, `embedding_config.py:64-68`, `docling_pipeline.py:42-46` | Configuration comes from environment reads scattered through modules; `OLLAMA_URL` is frozen at import. Introduce one frozen `AppConfig` built at the composition root. |
| Medium | `models.py:204` + `main.py:400` | Context budgeting runs twice: `main.py` trims with `atomic_indices`, then `stream_chat` trims again without them. It is a no-op today only because both passes use the same estimate and limit. Budgeting needs a single owner. |
| Low | backend | No logging exists anywhere in `lab/`. Failures leave no server-side evidence for a debugging agent. |

**Per module**

| Module | Severity | Finding |
| --- | --- | --- |
| `parse_pipeline.py` | Medium | `parse_and_persist` (35-207) interleaves parsing, tokenizer resolution, record building, asset writes, manifest building and update building. Figure-caption records (121-132) duplicate `_indexed_record` instead of using it. `chunk_id` is computed, then overwritten after the record is built (95-101), so the suffix and `chunk_index` can differ. It imports the private `_enforce_embed_limit` (9) and `content_hash` from `index` (13). |
| `parse_pipeline.py:215` + `docling_pipeline.py:90` | Medium | Extraction status is inferred by substring-matching warning prose (`"partial_success" not in warning`). This is a stringly typed cross-module contract. Emit structured warnings instead. |
| `chunking.py` | Low | An injected `chunker` skips embed-limit enforcement (108-109), another test seam that changes behavior. `_bbox_to_dict` is duplicated with `docling_pipeline.py:75`. Imports are absolute `lab.` while elsewhere they are relative. |
| `embedding_config.py` | Low | `DEFAULT_TOKENIZER_DIR` (18) is unused. `normalize_ollama_embed_error` (232) belongs in the model adapter. The module-level `lru_cache` of tokenizers is acceptable as memoized read-only loading; document it as such. |
| `index.py` | Medium | `class IndexError(ValueError)` (19) shadows the builtin, so `except IndexError` means different things in different files. Every return is `dict[str, Any]` although `contracts.IndexedChunk` exists. The constructor (170-178) creates the directory, database and migrations, so opening an index has side effects. |
| `retrieval.py` | Medium | D1. The query is embedded (72-81) before the index-existence check (82-84), wasting a serialized model call. Fallback mode is encoded as the sentinel `fusion.score == 0.0` (92-103). `evidence_messages` (115-167) mixes image file reads with pure formatting. |
| `models.py` | Medium | The local-model resolution sequence (tags, find, remote check, show, remote check) is duplicated in `embed_texts` (168-176) and `stream_chat` (209-220). Payload and think validation (223-234) should be pure functions. `context_capacity` (122) is a constant with an unused parameter. The local import at 183 is unnecessary. `except (..., TypeError, KeyError)` (271) turns programming errors into user-facing stream errors. |

### 5.3 Status of the 30 September refactor ([handoff](refactor-handoff.md))

| Work item | Status | Evidence |
| --- | --- | --- |
| 1. Typed data contracts | Partial | `contracts.py` exists and is used by `parse_pipeline` and `retrieval` signatures. `index.py` still returns `dict[str, Any]`; the file, topic, session and settings records are untyped; `store` is untyped. |
| 2. Decisions separated from effects | Partial | Ranking fusion is pure. `parse_and_persist`, `evidence_messages` and chat prompt assembly still interleave decisions and I/O. |
| 3. Explicit dependencies and resource ownership | Mostly done | `_GENERATION_LOCK` was replaced by `app.state.model_generation_lock` and one tokenizer is used per ingest. The clock, IDs and configuration are still implicit. The lock is bypassed whenever a backend is injected, so it is untested at the API level. |
| 4. Narrow errors | Done, with a regression | Narrowed to `httpx.HTTPError` and the "atomic" claim was corrected, but the "model not installed" outage (D1) was left unclassified. |
| 5. Callers and docs aligned | Partial | `architecture.md` is updated. `services/api/README.md:20-22` still describes a positional `stream_chat` contract and says "the model adapter owns truncation"; line 13 omits the Docling artifacts and `retrieval.sqlite`. The handoff status line claims completion. |

### 5.4 Backend tests and safety net

- Tests protect: path safety, original preservation, upload validation, context trimming, stream parsing, ranking, prefixing, chunk splitting, citation persistence, the missing-index error, and the busy-topic rejection.
- Gaps that make refactoring risky:
  - Fakes do not use the production gateway signature.
  - Nothing covers D1, D5, or stuck `processing` records.
  - There is no direct test of prompt ordering (evidence reversal, goal placement) independent of HTTP.
  - Nothing covers lock release when a client disconnects.
- Hygiene: backend tests are split across `services/api/tests/` and the repository-level `tests/` (`test_context.py`, `test_models.py`). `FakeModel` is duplicated. `conftest.py` and four scripts use `sys.path` hacks. `test_context.py` uses unittest style while the rest use pytest.

## 6. Tooling, CI and agent infrastructure

| Severity | Finding |
| --- | --- |
| High | **The conventions are not machine-enforced.** Ruff selects only `E9, F63, F7, F82` (`ruff.toml`). Formatting applies to three setup scripts only. TypeScript has no formatter or linter. `check_engineering.py` validates agent wiring and doc links only, and `engineering.md` says purity and cohesion "require review". With humans out of the loop, every rule that can be checked must be. |
| High | **There are no frontend conventions.** `engineering.md`'s functional rules are written for Python (Pydantic, ASGI). Nothing covers React state, effects, component size or formatting. |
| Medium | **Documentation drift misleads agents:** `services/api/README.md:13, 20-22`, `apps/web/README.md:14`, the handoff status line, and the ownership table in `architecture.md:15`, which assigns "workspace, files, settings, conversation" to `main.tsx` and so codifies the monolith. |
| Medium | The end-to-end check exercises only the legacy path. `verify_workspace.py` uploads with MarkItDown; the default Docling, indexing and chat paths are covered only in-process with fakes that bypass production branches. This is acceptable without models in CI, but the fakes must at least use the production signature. |
| Medium | **Harness mismatch.** `AGENTS.md:10-11` routes work to Codex roles with fixed models. In Cursor those configs cannot be spawned; only the skill procedures carry over. `AGENTS.md:24` limits subagents to explicit requests, which conflicts with the goal of high-trust autonomy. The policy needs a decision. |
| Low | `dev.py` and `verify_workspace.py` duplicate port, readiness and stop helpers. |
| Low | The skills are thin (one paragraph each). There is no behavior-preserving refactor procedure: characterization tests first, mechanical commits separate, `git diff -w` checks, one writer per file. |

## 7. Refactor plan

The rule for every slice: **behavior-preserving, one writer per path, characterization tests land before the code they protect, mechanical changes (formatting, moves) in their own commits.** Keep the API contract (`docs/API.md`) and stored formats frozen throughout; stored-format changes need a separate compatibility decision.

### Phase 0 — decisions that need Tanmay (once)

1. Frontend tooling. Recommended: Prettier plus ESLint with `react-hooks` and `no-empty`, and Vitest with Testing Library and jsdom in place of the `data:`-URL harness. Vitest already fits Vite.
2. Runtime validation at the browser boundary: hand-written guards versus `zod`.
3. Recovery policy for stuck `processing` records (D4).
4. Subagent and harness policy in `AGENTS.md` (section 6).
5. Size budgets to enforce. Proposed: TSX/TS lines at most 120 characters; component files at most 250 lines; Python function complexity at most 10 with a ratchet list for current offenders.

Decided by Tanmay on 1 October 2026:

- Decision 1: Prettier, ESLint with `react-hooks`, and Vitest with Testing Library, as recommended.
- Decision 3: when a record in `processing` is read after an interruption, mark it `error` with the reason "interrupted" and keep every artifact.
- Decision 4: the coordinator may start any role within an approved plan. This is recorded in `AGENTS.md`.
- Decision 2: use `zod` schemas in `api.ts` as the single source of both TypeScript types and runtime checks, including NDJSON stream events.
- Decision 5: automatic formatting only (Prettier and `ruff format`). There are no enforced limits on line, file, function or complexity size. Split files when they become a real problem, never to satisfy a number. The structural refactor slices below stand on their own design merits.

### Phase 1 — defect fixes (sequential, each with a regression test)

| Slice | Role(s) | Owned paths | Acceptance |
| --- | --- | --- | --- |
| P1-a: fix D1 | code, review | `models.py`, `retrieval.py`, the retrieval tests | A typed `EmbeddingUnavailable` (model not installed, or transport failure) degrades to a keyword index or keyword search with a warning. Oversize and data errors still fail loudly. Regression tests cover upload and chat with the model missing. |
| P1-b: investigate D5 | debug, then code | reproduction test only, then `main.py` | A failing test reproduces the lock leak on an early disconnect, or D5 is refuted with evidence. |
| P1-c: fix D2 | code | `main.tsx` (minimal edit) | Goal state resets on topic change; save requires `topicReady`. |
| P1-d: fix D3 | code | `storage.py`, `main.py` upload write | An exclusive-create, fsynced original write exists; an existing name is never overwritten. |
| P1-e: fix D4 | design, then code | per the decision | Interrupted records become visible and recoverable. |
| P1-f: docs drift | code | the two READMEs, the handoff status | Every claim matches the code. |

### Phase 2 — guardrails (before any structural slice)

| Slice | Owned paths | Acceptance |
| --- | --- | --- |
| G-1: Python lint ratchet | `ruff.toml`, CI | Add the correctness rules `BLE001, A001, B, ANN001/ANN201` for `services/api/lab`, with per-file ignores listing today's offenders. Removing an ignore is the done-signal for later slices. No size or complexity rules (decision 5). |
| G-2: Python format | whole Python tree | One mechanical `ruff format` commit; `git diff -w` shows no semantic change; tests pass. |
| G-3: TypeScript format and lint | `apps/web` configs, `package.json`, CI | Prettier over `src/` in one mechanical commit (it turns `main.tsx` into readable lines, so all later diffs are reviewable). ESLint `react-hooks/*`, `no-empty`; `noImplicitReturns`. |
| G-4: frontend test harness | `apps/web/tests`, `vitest.config.ts` | Existing 18 tests ported unchanged in intent; modules may value-import each other. |
| G-5: structural checks | `scripts/check_engineering.py` | Fail on: `fastapi` imported outside the HTTP layer; `os.environ` outside the config module; `catch {}` or `except Exception` without an allow-list entry. |
| G-6: conventions | `docs/engineering.md`, review checklist, `AGENTS.md` | Add a frontend section, a ban on test-only branches in production code, the error taxonomy, configuration ownership, and a behavior-preserving refactor procedure. |

### Phase 3 — frontend track (single writer on `apps/web/src`, sequential)

| Slice | Owned paths | Acceptance |
| --- | --- | --- |
| FE-0: characterization tests | `apps/web/tests/` | Testing Library tests for topic switch and reset, send/stream/stop, stream error and incomplete marking, upload-blocked states, drag-drop, model-select success and mismatch, settings save, goal save, and preview. They pass on current code. |
| FE-1: pure extraction | `src/state/*`, `src/domain/*`, `src/api/*` | `applyStreamEvent`, activity machine, topic-session reducer, file rules, and one URL module, each unit-tested. Remove dead code (`citationLocation`, `modelContextMax`, `fileAssetPath`); unify mode labels and error parsing. |
| FE-2: hooks own effects | `src/hooks/*`, `App.tsx`, `main.tsx` | `App` holds no `fetch`, `localStorage` or `window` calls; refs remain only for DOM and `AbortController`. |
| FE-3: components | `src/components/*` | Each component has one responsibility; shared `VisualAssets` replaces the two duplicates; `main.tsx` holds `createRoot` only. |
| FE-4: boundary validation | `src/api/client.ts`, `types.ts` | Responses and stream events are validated; statuses are unions shared by the domain rules. |
| Exit | — | FE-0 tests unchanged and passing; `make build`; usage-skill browser run of [flows](../../.agents/skills/usage/references/flows.md). |

### Phase 4 — backend track (runs in parallel with Phase 3; disjoint paths)

Order: BE-0 → BE-1 → BE-2 → BE-3 → BE-4 → {BE-5, BE-6, BE-7 in parallel} → BE-8.

| Slice | Owned paths | Acceptance |
| --- | --- | --- |
| BE-0: characterization | `services/api/tests/` (+ shared `fakes.py`) | Fakes implement the production gateway signature. Direct tests cover prompt ordering and goal placement, citation and evidence agreement after trimming, the upload record transitions, and lock release on every exit path. |
| BE-1: error taxonomy | new `lab/errors.py`; `storage`, `index`, `retrieval`; the handler in `main.py` | No `fastapi` import outside the HTTP layer; identical status codes and messages; rename `IndexError`. |
| BE-2: contracts | `contracts.py`, annotations across `lab/` | `FileRecord` (status Literals), `TopicRecord`, `Session`/`Message`, `ExtractionDiagnostics`, a `ModelGateway` Protocol and a `Store` Protocol. The file record's JSON shape is unchanged. The Ruff `ANN` ignores for `lab/` are gone. |
| BE-3: configuration | new `lab/config.py`, `models.py`, `docling_pipeline.py`, `embedding_config.py`, `scripts/*` | A frozen `AppConfig` is built once. Importing `lab.main` has no side effects: the app entry point moves to `lab/asgi.py` or `uvicorn --factory`, with `dev.py` and `verify_workspace.py` updated. `OLLAMA_URL` comes from configuration. |
| BE-4: split `main.py` | `lab/http/{app,topics,files,chat,settings}.py`, `lab/ingest.py`, `lab/chat_prompt.py`, `lab/chat_session.py` | Thin routers. Pure `build_chat_prompt`, `retained_citations`, the upload-record transition functions, and session transitions that return new values. Injected dependencies all follow the production path (a parser map replaces the `converter` branch; there is one gateway call signature). The lock lifecycle is owned by one context manager covering D5. |
| BE-5: ingestion | `parse_pipeline.py`, `chunking.py`, `docling_pipeline.py`, the ingest call site | Pure record, manifest and update builders; structured parser warnings; one record builder for text and figure chunks; public `enforce_embed_limit`; `content_hash` moves out of `index.py`. Chunk JSONL is byte-identical on the synthetic fixture. |
| BE-6: retrieval | `retrieval.py`, `index.py`, the chat call site | Typed hits; an explicit fallback flag instead of the 0.0 sentinel; the index is checked before embedding; image loading is separated from evidence formatting. |
| BE-7: model adapter | `models.py` | Shared local-model resolution; pure payload and think validation; single-owner budgeting (the adapter asserts the prompt fits rather than re-trimming); narrowed excepts. |
| BE-8: hygiene | tests, scripts | One backend test root; no `sys.path` hacks; shared process helpers for scripts; dead code removed; the `architecture.md` ownership table rewritten for the new module map. |
| Exit | — | `make test`, `make build`, full Ruff with no remaining ratchet entries for touched modules, `check_engineering.py`, `verify_workspace.py`, an isolated Docling smoke if models are installed, and a usage-skill browser run. |

### Why this order matters for R1

Several saved conversations (R1 item 4) need typed session records and API projections separate from storage (BE-2, BE-4). LangGraph tools and approvals (items 7-8) need storage and retrieval functions that raise domain errors rather than HTTP errors, a pure prompt builder usable as a graph node, and one model gateway protocol (BE-1, BE-4, BE-7). Topic memory and restart recovery (item 10) needs deliberate state transitions and the recovery policy from D4. Building those features before this refactor would multiply the current hotspots.

## 8. Confirmed versus unverified

- **Confirmed by execution:** D1, in an isolated temporary store. Also measured: Ruff complexity and statement counts, blind-except locations, TypeScript `noImplicitReturns`, diff-churn and line-length measurements, and the Starlette 1.6.0 `StreamingResponse` lifecycle source.
- **Confirmed by reading:** D2, D3, D4, the test-only branches, double budgeting, stale docs, duplicated components and helpers, and dead code.
- **Unverified:** whether "Refresh files" clearing the input and selection is intended; browser behavior. No Docling model or browser session was exercised in this review.
- **Resolved after the review (1 October 2026):** D5 was confirmed by a reproduction test and fixed. The D1 fix was verified against live local Ollama.
- **Not assessed:** styling and accessibility beyond code structure (the modals lack a focus trap and Escape handling, noted only), performance of pure-Python vector scoring at scale, and the vendored parser skills under `skills/`, which are pinned references rather than application code.
