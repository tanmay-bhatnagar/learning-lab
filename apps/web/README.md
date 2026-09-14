# Learning Lab frontend

React, TypeScript, and Vite browser workspace. All data comes from the backend API; no mock model responses or automatic model downloads.

```sh
npm install
npm run dev
npm run build
node --test tests/stream.test.mjs
```

Dev server: http://127.0.0.1:5173. Vite proxies `/api` to `LEARNING_LAB_API_URL`, supplied by `make dev` when it chooses a free backend port; running Vite alone defaults to `http://127.0.0.1:8765`. Production deployments need an equivalent same-origin `/api` route. Build output is `dist/`.

The interface supports one conversation per topic, explicit attachment selection, PDF upload with MarkItDown or AnyDoc, original PDF and safe Markdown inspection, NDJSON thinking/answer streaming, partial-response indicators (`incomplete`), context usage, and saved settings. Context defaults to 8192 and is capped at 32768. Thinking capabilities come from the live model API. Model preferences persist through backend settings; thinking preferences persist per model in browser storage. Cloud provider placeholders are disabled.

Markdown skips raw HTML, uses the renderer's safe URL handling, and replaces all images with inert text placeholders. No external font or image requests are initiated. External links open only when clicked. Original PDFs use the topic-scoped inline PDF endpoint.

Backend owns persistence, cancellation behavior, parsing, context trimming, and model execution. Older input can leave model context while durable history remains. Interrupted streams display partial output honestly; reloading retrieves authoritative saved history.
