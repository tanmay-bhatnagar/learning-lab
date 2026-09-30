# Learning Lab frontend

React, TypeScript, and Vite browser workspace. All data comes from the backend API; no mock model responses or automatic model downloads.

```sh
npm install
npm run dev
npm run build
npm test
```

Dev server: http://127.0.0.1:5173. Vite proxies `/api` to `LEARNING_LAB_API_URL`, supplied by `make dev` when it chooses a free backend port; running Vite alone defaults to `http://127.0.0.1:8765`. Production deployments need an equivalent same-origin `/api` route. Build output is `dist/`.

The interface supports one conversation per topic, a per-topic learning goal, explicit attachment selection, PDF upload (Docling by default, with MarkItDown and AnyDoc as fallbacks), original PDF and safe Markdown inspection, per-file extraction diagnostics, index mode and warnings, NDJSON thinking/answer streaming, partial-response indicators (`incomplete`), context usage, and saved settings.

Answers from indexed files show their sources: file, headings and page links that open the original PDF at the cited page. The retrieval trace tab runs a query against the selected indexed files and shows keyword, embedding and fused ranks with linked figures.

Context defaults to and is capped at the app maximum of 32,768 tokens, whatever a model advertises. Thinking capabilities come from the live model API. Model selection immediately persists through backend settings and blocks chat/settings changes until the response arrives. Success is shown only after the returned model matches the selection; chat uses the saved selection. Other settings retain their explicit Save action. Readable model labels use the API display name with a local fallback, and technical IDs remain available in tooltips. Assistant labels use only returned model metadata, including saved history. Explicit saved parser preferences remain authoritative. The attached-files area accepts PDF drops and keyboard browsing, validates the entire batch (extension, MIME type when supplied, nonempty size, 25 MiB maximum, and PDF header), and prevents duplicate concurrent uploads and browser file navigation. Thinking preferences persist per model in browser storage. Cloud provider placeholders are disabled.

Markdown skips raw HTML, uses the renderer's safe URL handling, and replaces all images with inert text placeholders. No external font or image requests are initiated. External links open only when clicked. Original PDFs and figures use topic-scoped API endpoints.

Backend owns persistence, cancellation behavior, parsing, retrieval, context trimming, and model execution. Older input can leave model context while durable history remains. Interrupted streams display partial output honestly; reloading retrieves authoritative saved history.
