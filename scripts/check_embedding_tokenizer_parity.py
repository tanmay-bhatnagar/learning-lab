#!/usr/bin/env python3
"""Compare local embedding tokenizer counts with Ollama prompt_eval_count."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

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


def _ensure_api_on_path() -> None:
    api_root = str(ROOT / "services/api")
    current = os.environ.get("PYTHONPATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    if api_root in parts:
        return
    os.environ["PYTHONPATH"] = os.pathsep.join([api_root, *parts])
    os.execv(sys.executable, [sys.executable, *sys.argv])


_ensure_api_on_path()


async def _ollama_counts(base_url: str, model: str, texts: list[str]) -> list[int | None]:
    import httpx

    counts: list[int | None] = []
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        trust_env=False,
        timeout=httpx.Timeout(300, connect=5),
    ) as client:
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
    base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
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
        ollama_counts = asyncio.run(_ollama_counts(base_url, model, texts))
    except Exception as exc:  # noqa: BLE001 - any Ollama failure is reported, not fatal
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
                "ollama_base_url": base_url.rstrip("/"),
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
