# Retrieval evaluation

Each gold set references one of the three existing public PDFs registered in `docs/eval_pdf_selection.json`, by exact path and SHA-256. Tanmay reduced the original five-paper selection to its first three; no redraw was made. Build and verify one PDF at a time. Whisper is the default manifest; choose another completed gold set with `--manifest`.

The source-backed gold sets are `whisper.v1.json`, `janus.v1.json`, and `caviar.v1.json`. Harness regressions are in `services/api/tests/test_retrieval_eval.py`. See [validation](../../docs/retrieval_eval_validation.md) for the recorded real-paper baselines and coverage limits.

Run one manifest at a time from the Code repository. The default keyword baseline is:

```sh
.venv/bin/python -m evals.retrieval.runner --mode keyword
```

The runner creates a unique isolated workspace below ignored `.local/evals/`, uploads the immutable source through the production Docling route, reads indexed text from the production topic index, and sends each question through the production chat route with the same production retrieval function wrapped only to capture its return value. Each run copies the configured runtime policy (by default the parent `AGENTS.md`) to `runtime-policy.md` and records its SHA-256 in result provenance. The app receives that snapshot by explicit path, so later policy edits cannot change an in-progress run. The injected generator emits fixed simulated text. Answer quality and abstention behavior are not tested. The isolated workspace contains ordinary saved histories and parsed/indexed artifacts; the compact result and production query traces omit questions, prompts, passages, and generated text.

The default context limit is 16,384 tokens to accommodate the full runtime policy together with the fixed capability rules and ordinary learning context. A smaller explicit limit remains honored and recorded; if the policy and prompt do not fit, the evaluation fails visibly and saves the policy hash and failure status. For a separately configured policy, pass `--runtime-policy /path/to/AGENTS.md`; the path is read once and its exact bytes are preserved in the run snapshot.

The result separates indexed anchor coverage from retrieval and retained-evidence coverage. A missing indexed anchor makes that case extraction-limited with null retrieval metrics; it does not become a retrieval miss or a pass, and the runner exits nonzero for extraction-limited readiness. This can mean an extraction omission or an unresolved representation difference; inspect the original and indexed text before diagnosing loss. Unsupported cases have null retrieval metrics and `abstention: not_assessed`. Baseline retrieval misses remain visible but do not fail a quality gate; `quality_gate_applied` is false.

Anchors require the physical PDF page and all phrases in an alternative within one indexed chunk. Alternatives are OR; evidence groups are AND. Matching normalizes Unicode typography, whitespace, line-break hyphenation, and table delimiters, with token/number boundaries. Numeric table facts retain their row, column, and table associations. Recall uses fixed evidence-group denominators; reciprocal rank uses the first relevant retrieval rank. Retained metrics preserve those original ranks rather than re-ranking the surviving prompt messages. These are anchor-based coverage measures, not semantic correctness or precision.

An optional local hybrid run is available only when the requested embedding model is already installed:

```sh
.venv/bin/python -m evals.retrieval.runner --mode hybrid
```

Choose a specific paper explicitly:

```sh
.venv/bin/python -m evals.retrieval.runner --manifest evals/retrieval/janus.v1.json --mode hybrid
.venv/bin/python -m evals.retrieval.runner --manifest evals/retrieval/caviar.v1.json --mode hybrid
```

Run these separately; there is no batch parser. The runner checks local Ollama tags before parsing and never downloads a model. Hybrid index degradation is a hard infrastructure failure. Outputs include source and manifest hashes, the dirty source-file fingerprint captured before parsing, parser/dependency versions, index mode, embedding digest when reported, and per-case invariant failures. Results remain in ignored `.local/evals/`; remove the isolated run directory after review if it is no longer needed.

To rerun questions after changing gold anchors or scorer checks without parsing the PDF again, pass the completed run directory. The runner validates its source and parser/index metadata, stages a fresh isolated copy of the topic and settings, and writes replay histories, traces, and results under a new run ID; it leaves the prepared run untouched:

```sh
.venv/bin/python -m evals.retrieval.runner --prepared-run .local/evals/<run-id>
```

Prepared replay inherits mode, top-k, and context limit from the source run. If explicitly supplied, those values must match the prepared index and stored settings. It uses a fresh snapshot of the currently configured runtime policy, so the policy hash may differ from the prepared run. Older prepared runs with a context limit too small for the current policy will fail with a recorded context-budget error; use a fresh evaluation at the default context limit to establish a new baseline. The PDF identity must also match. Prior parser/index provenance stays separate from the current evaluator fingerprint. Failures after workspace creation retain a sanitized failure artifact and requested provenance; command-line or manifest failures before creation are reported on stderr.

Fast harness regressions live in `services/api/tests/test_retrieval_eval.py` and run with the ordinary backend tests. They cover scorer math and false matches, malformed inputs, source/path boundaries, prepared replay, failed-run provenance, trace mutations, production chat/retrieval integration, and tight-context rejection. They use isolated small fixtures; the explicit evaluation commands use the selected real PDFs and installed local assets.

Results are descriptive pilot artifacts, not a quality gate or a claim about answer accuracy. Review extraction gaps and individual evidence-group misses before interpreting aggregate scores.
