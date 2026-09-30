# Learning Lab verification flows

Launch: `.venv/bin/python scripts/verify_workspace.py --serve`. Use the printed browser URL and evidence directory. Never use the user's existing instance. The launcher overrides learning/settings roots and retains logs/evidence under `.local/verification/`. Browser mode needs port 5173 free because the application restricts browser write origins to that port; an occupied port causes a clear failure, never a process kill. The default HTTP check uses dynamic ports. Ctrl-C stops its owned services. If it fails, inspect those logs; do not kill processes by name or reuse an unverified port.

Doctor: request `/api/health` through the printed browser URL; confirm the initially isolated topics list and the evidence metadata point at this run. Automatic verification may already have created a synthetic topic. Do not infer isolation from a page title alone.

| Flow | Drive | Observable proof |
| --- | --- | --- |
| Topic | Create a uniquely named topic through the UI, then reload | Same topic returns; persisted records exist only in this run's root |
| PDF | Upload the generated fixture shown by the launcher using MarkItDown | Markdown contains calibration value 42; original bytes match; UI shows successful conversion |
| Invalid upload | Attempt a non-PDF through the attachment control | Visible rejection; no ready attachment is created |
| Settings | Change a supported value, save, reload | Saved value returns; unavailable models are reported, not silently substituted |
| Chat (requires installed model) | Select fixture and an installed model, ask its calibration value | Response uses selected model, answers 42, history survives reload |
| Evidence (when implemented on this revision) | Ask two document questions, inspect first answer's sources, reload | First answer retains its own sources and valid file/page associations |
| Isolation | Inspect generated topic/state paths | No personal topic was accessed or modified |

Save actions, expected/actual outcomes, screenshots where useful, and artifact observations in the printed evidence directory. Do not erase evidence during teardown. Record untested flows, unavailable models, and missing revision-specific features explicitly. Neither the automated HTTP smoke nor a screenshot alone proves the whole browser journey.

Use real-model and structured-parser checks only for relevant changes and available local dependencies. Do not automatically download models or run the full benchmark corpus.
