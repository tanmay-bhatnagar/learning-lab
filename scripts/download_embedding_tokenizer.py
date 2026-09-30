#!/usr/bin/env python3
"""Download or bootstrap the offline embedding tokenizer for nomic-embed-text.

Primary source: Hugging Face bert-base-uncased (matches nomic-embed-text v1.5).
Fallback: extract tokenizer.ggml.tokens from the local Ollama nomic-embed-text GGUF
blob and materialize a Bert-compatible vocab under data/external/modelweights/tokenizers/.
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data/external/modelweights/tokenizers/bert-base-uncased"
HF_REPO = "bert-base-uncased"
TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "config.json",
    "special_tokens_map.json",
)

GGUF_TYPE_STRING = 8
GGUF_TYPE_ARRAY = 9


def _gguf_scalar_size(vtype: int) -> int | None:
    return {
        0: 1,
        1: 1,
        2: 2,
        3: 2,
        4: 4,
        5: 4,
        6: 4,
        7: 1,
        10: 8,
        11: 8,
        12: 8,
    }.get(vtype)


class _GGUFReader:
    def __init__(self, stream):
        self._stream = stream

    def _read(self, size: int) -> bytes:
        data = self._stream.read(size)
        if len(data) != size:
            raise RuntimeError("Unexpected EOF while reading GGUF metadata.")
        return data

    def u32(self) -> int:
        return struct.unpack("<I", self._read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self._read(8))[0]

    def key_str(self) -> str:
        return self._read(self.u64()).decode("utf-8")

    def val_str(self) -> str:
        return self._read(self.u64()).decode("utf-8")

    def read_value(self, vtype: int):
        if vtype == GGUF_TYPE_STRING:
            return self.val_str()
        if vtype == GGUF_TYPE_ARRAY:
            elem_type = self.u32()
            count = self.u64()
            if elem_type == GGUF_TYPE_STRING:
                return [self.val_str() for _ in range(count)]
            elem_size = _gguf_scalar_size(elem_type)
            if elem_size:
                self._stream.seek(int(count) * elem_size, os.SEEK_CUR)
                return None
            raise RuntimeError(f"Unsupported GGUF array element type {elem_type}.")
        size = _gguf_scalar_size(vtype)
        if size:
            self._stream.seek(size, os.SEEK_CUR)
            return None
        raise RuntimeError(f"Unsupported GGUF value type {vtype}.")

    def skip_value(self, vtype: int) -> None:
        self.read_value(vtype)


def _extract_gguf_tokens(path: Path) -> list[str]:
    with path.open("rb") as stream:
        reader = _GGUFReader(stream)
        if reader._read(4) != b"GGUF":
            raise RuntimeError(f"Not a GGUF file: {path}")
        version = reader.u32()
        if version >= 2:
            reader.u64()  # n_tensors
            n_kv = reader.u64()
        else:
            reader.u32()
            n_kv = reader.u32()
        for _ in range(n_kv):
            key = reader.key_str()
            vtype = reader.u32()
            if key == "tokenizer.ggml.tokens":
                tokens = reader.read_value(vtype)
                if not isinstance(tokens, list) or not tokens:
                    raise RuntimeError("tokenizer.ggml.tokens missing or empty.")
                return tokens
            reader.skip_value(vtype)
    raise RuntimeError(f"tokenizer.ggml.tokens not found in {path}")


def _find_nomic_gguf() -> Path | None:
    manifests = ROOT / "data/external/modelweights/manifests/registry.ollama.ai/library/nomic-embed-text"
    if not manifests.is_dir():
        return None
    for tag in manifests.iterdir():
        if not tag.is_file():
            continue
        manifest = json.loads(tag.read_text(encoding="utf-8"))
        for layer in manifest.get("layers", []):
            if layer.get("mediaType") == "application/vnd.ollama.image.model":
                digest = layer["digest"].split(":", 1)[-1]
                candidate = ROOT / f"data/external/modelweights/blobs/sha256-{digest}"
                if candidate.is_file():
                    return candidate
    return None


_SPECIAL_TOKEN = re.compile(r"^\[[A-Za-z0-9_]+\]$")
_GGUF_WORD_START = "\u2581"


def _gguf_to_wordpiece(tokens: list[str]) -> list[str]:
    """Invert llama.cpp's BERT vocab conversion.

    GGUF stores word-initial pieces as "\u2581piece" and continuation pieces
    without the "##" marker; BertTokenizer expects the opposite.
    """
    converted = []
    for token in tokens:
        if token.startswith(_GGUF_WORD_START):
            converted.append(token[len(_GGUF_WORD_START) :])
        elif _SPECIAL_TOKEN.match(token):
            converted.append(token)
        else:
            converted.append(f"##{token}")
    if len(set(converted)) != len(converted):
        raise RuntimeError("GGUF vocab conversion produced duplicate WordPiece tokens.")
    return converted


def _write_bert_vocab(tokens: list[str], target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "vocab.txt").write_text("\n".join(_gguf_to_wordpiece(tokens)) + "\n", encoding="utf-8")
    (target / "tokenizer_config.json").write_text(
        json.dumps(
            {
                "do_lower_case": True,
                "model_max_length": 512,
                "tokenizer_class": "BertTokenizer",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    pad_token = "[" + "PAD" + "]"
    unk_token = "[" + "UNK" + "]"
    (target / "special_tokens_map.json").write_text(
        json.dumps(
            {
                "cls_token": "[CLS]",
                "mask_token": "[MASK]",
                "pad_token": pad_token,
                "sep_token": "[SEP]",
                "unk_token": unk_token,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (target / "config.json").write_text(
        json.dumps({"model_type": "bert"}, indent=2) + "\n",
        encoding="utf-8",
    )
    # Materialize tokenizer.json via transformers when available.
    sys.path.insert(0, str(ROOT / "services/api"))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    from transformers import BertTokenizer

    tokenizer = BertTokenizer.from_pretrained(str(target), local_files_only=True)
    tokenizer.save_pretrained(str(target))


def _download_from_hf(target: Path) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        HF_REPO,
        local_dir=str(target),
        allow_patterns=list(TOKENIZER_FILES),
    )


def _is_complete(target: Path) -> bool:
    return all((target / name).is_file() for name in TOKENIZER_FILES)


def main() -> None:
    target = Path(os.environ.get("EMBEDDING_TOKENIZER_DIR", DEFAULT_DIR)).expanduser()
    if _is_complete(target):
        print(json.dumps({"status": "ready", "path": str(target.resolve()), "source": "existing"}))
        return

    errors: list[str] = []
    try:
        _download_from_hf(target)
        if _is_complete(target):
            print(json.dumps({"status": "ready", "path": str(target.resolve()), "source": "huggingface"}))
            return
        errors.append("Hugging Face download did not materialize all tokenizer files.")
    except Exception as exc:
        errors.append(f"Hugging Face: {type(exc).__name__}: {exc}")

    gguf = _find_nomic_gguf()
    if gguf is None:
        errors.append("Local Ollama nomic-embed-text GGUF blob not found.")
        raise SystemExit(json.dumps({"status": "error", "errors": errors}, indent=2))

    try:
        tokens = _extract_gguf_tokens(gguf)
        _write_bert_vocab(tokens, target)
        if not _is_complete(target):
            raise RuntimeError("Bootstrap from GGUF did not produce a complete tokenizer directory.")
        print(
            json.dumps(
                {
                    "status": "ready",
                    "path": str(target.resolve()),
                    "source": "ollama-gguf",
                    "gguf": str(gguf.resolve()),
                    "token_count": len(tokens),
                    "warnings": errors,
                },
                indent=2,
            )
        )
    except Exception as exc:
        errors.append(f"GGUF bootstrap: {type(exc).__name__}: {exc}")
        raise SystemExit(json.dumps({"status": "error", "errors": errors}, indent=2))


if __name__ == "__main__":
    main()
