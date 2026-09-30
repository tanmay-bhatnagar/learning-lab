#!/usr/bin/env python3
"""Compare local embedding tokenizer counts with Ollama prompt_eval_count."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))

SAMPLES = [
    ("plain", "hello world"),
    ("document_prefix", "search_document: hello world"),
    ("query_prefix", "search_query: What is calibration?"),
    (
        "longer_document",
        "search_document: The pre-amplifier stage rescales millivolt-level transducer output "
        "before downstream normalization and digitization.",
    ),
    ("unicode_and_symbols", "naïve café résumé, Z7X-CAL-9001 and softmax(QK^T/√d_k)V — 日本語 😀"),
]


async def _ollama_counts(model: str, texts: list[str]) -> list[int | None]:
    import httpx
    from lab import models

    counts: list[int | None] = []
    async with models._client() as client:
        for text in texts:
            try:
                response = await client.post(
                    "/api/embed",
                    json={"model": model, "input": [text], "truncate": False, "keep_alive": 0},
                )
                if response.status_code != 200:
                    counts.append(None)
                    continue
                body = response.json()
                count = body.get("prompt_eval_count")
                counts.append(count if isinstance(count, int) else None)
            except httpx.HTTPError:
                counts.append(None)
    return counts


def main() -> None:
    from lab.embedding_config import count_embedding_tokens, tokenizer_path

    model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
    path = tokenizer_path(model)
    if path is None or not path.is_dir():
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "embedding tokenizer not configured or missing",
                    "hint": "Run `make embedding-tokenizer` from Code.",
                },
                indent=2,
            )
        )
        return

    rows = []
    texts = [text for _, text in SAMPLES]
    local_counts = [count_embedding_tokens(text, model) for text in texts]
    try:
        ollama_counts = asyncio.run(_ollama_counts(model, texts))
    except Exception as exc:
        ollama_counts = [None] * len(texts)
        ollama_error = f"{type(exc).__name__}: {exc}"
    else:
        ollama_error = None

    for (label, text), local, ollama in zip(SAMPLES, local_counts, ollama_counts, strict=True):
        rows.append(
            {
                "label": label,
                "text_chars": len(text),
                "local_tokens": local,
                "ollama_prompt_eval_count": ollama,
                "delta": (local - ollama) if isinstance(ollama, int) else None,
            }
        )

    print(
        json.dumps(
            {
                "status": "ok",
                "model": model,
                "tokenizer_path": str(path.resolve()),
                "ollama_error": ollama_error,
                "samples": rows,
                "note": "Local counts use encode(..., add_special_tokens=True); expect delta 0 for every sample.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
