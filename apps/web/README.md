# Learning Lab frontend

React, TypeScript, and Vite browser workspace. All data comes from the backend API; no mock model responses or automatic model downloads.

```sh
npm install
npm run dev
npm run build
npm test
```

Dev server: http://127.0.0.1:5173. Vite proxies `/api` to `LEARNING_LAB_API_URL`, supplied by `make dev` when it chooses a free backend port; running Vite alone defaults to `http://127.0.0.1:8765`. Production deployments need an equivalent same-origin `/api` route. Build output is `dist/`.

The interface supports one conversation per topic, explicit attachment selection, PDF upload with MarkItDown or AnyDoc, original PDF and safe Markdown inspection, NDJSON thinking/answer streaming, partial-response indicators (`incomplete`), context usage, and saved settings. Context defaults to the app maximum of 32,768 tokens; a model advertising a lower maximum constrains both the default on selection and validation. Thinking capabilities come from the live model API. Model selection immediately persists through backend settings and blocks chat/settings changes until the response arrives. Success is shown only after the returned model matches the selection; chat uses the saved selection. Other settings retain their explicit Save action. Readable model labels use the API display name with a local fallback, and technical IDs remain available in tooltips. Assistant labels use only returned model metadata, including saved history. AnyDoc is the default parser for new settings; explicit saved parser preferences remain authoritative. The attached-files area accepts PDF drops and keyboard browsing, validates the entire batch (extension, MIME type when supplied, nonempty size, 25 MiB maximum, and PDF header), and prevents duplicate concurrent uploads and browser file navigation. Thinking controls follow API capabilities; thinking preferences persist per model in browser storage. Cloud provider placeholders are disabled.

Markdown skips raw HTML, uses the renderer's safe URL handling, and replaces all images with inert text placeholders. No external font or image requests are initiated. External links open only when clicked. Original PDFs use the topic-scoped inline PDF endpoint.

Backend owns persistence, cancellation behavior, parsing, context trimming, and model execution. Older input can leave model context while durable history remains. Interrupted streams display partial output honestly; reloading retrieves authoritative saved history.
