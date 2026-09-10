# Initial R1 foundation validation — 10 September 2026

Environment: macOS on M3 Pro, 36 GB unified memory, Python 3.13.3, Node 25.2.1, Ollama 0.33.3. Exact Python package versions are in `../services/api/requirements-macos-py313.lock`; browser packages are in `../apps/web/package-lock.json`.

## Passed

- 54 backend/model/context tests plus 13 parameterized subtests: topic persistence, immutable uploads, path and symlink rejection, cross-topic file rejection, untrusted browser origins/hosts, upload size limits, parser failures, partial chat retention, local/cloud model validation, thinking capabilities, stream parsing, oldest-input truncation, protected system messages, preserved attachment suffixes, and response-budget cutoff reporting.
- Four browser-client stream tests: split NDJSON, premature EOF, server errors, HTTP errors.
- TypeScript checking and Vite production build.
- `pip check`: no broken dependencies.
- Real synthetic PDF converted by both MarkItDown 0.1.7 and firecrawl-anydoc 0.2.4; extracted calibration value verified; original PDF bytes unchanged.
- Real streamed PDF-grounded answers from `qwen3.5:4b-q8_0` and `qwen3.5:9b-q4_K_M`, with thinking disabled. Saved history and runtime context counts verified.
- Browser workflow in a separate temporary Learning root: create topic, upload via anydoc, inspect Markdown and original PDF viewer, explicitly select the attachment, save Qwen configuration with thinking enabled, receive thinking and final answer, see measured usage (2,166 / 8,192 in that run), reload saved conversation.
- Narrow-panel and desktop layouts inspected.

Downloaded local candidates: Qwen3.5 4B Q8 (5.28 GB download) and 9B Q4_K_M (6.59 GB download). Existing Gemma3 12B and DeepSeek R1 14B were discovered; this pass did not benchmark their generation. Qwen4 was observed using GPU inference in Ollama. This is functional validation, not a latency/quality or maximum-memory benchmark.

## Limits

Only a small synthetic, text-based PDF was used for integration checks. Parser quality on equations, complex tables, scanned pages and long real documents remains to be compared. No personal evidence was used for tests. Personal Learning folders remain unpopulated.

Reasoning can be verbose on small models. A generation-budget cutoff now reports an incomplete response and preserves partial output. The context meter reflects the latest request; preflight budgeting uses conservative estimates, not an exact tokenizer. No summarization or compaction exists.

This build is the local app/ingestion foundation. Full R1 retrieval, LangGraph learning tools and learning-progress workflows remain later increments. Model-executed tools, coding execution, external research, multimodal input and Jetson serving are not enabled.
