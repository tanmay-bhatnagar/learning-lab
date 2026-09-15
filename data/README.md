# Product data

The requested data-product directories are real and their contents are excluded from Git.

- `external/modelweights/`: Ollama's complete model store, including shared weight blobs and manifests. `~/.ollama/models` points here so the existing Ollama application and CLI continue to work. Model names are represented by manifests; shared blobs must not be split or renamed into per-model copies.
- `raw/`: original inputs for future explicitly authorized product evaluation datasets.
- `interim/`: intermediate extraction and evaluation outputs.
- `processed/`: final prepared product evaluation datasets and parser outputs.

Personal learning PDFs, derived Markdown and conversations still belong in `../../Learning/<topic>/`. These data directories do not expand the learning model's access permissions. The public parser-benchmark corpus is versioned in `external/benchmark_PDFs/`; temporary fetch material stays ignored.

Model store migration on 15 September 2026 was a filesystem rename, with original manifest bytes checked and the old path retained as a compatibility symlink. All four installed models remain discoverable. Model weights are data, not source code, and must never be committed.
