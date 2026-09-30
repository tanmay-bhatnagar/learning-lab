"""Offline embedding tokenizer registry, task prefixes, and token accounting."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

EmbedRole = Literal["document", "query"]

DEFAULT_CHUNK_TOKEN_LIMIT = 512
DEFAULT_EMBED_CONTEXT_LIMIT = 2048
EMBEDDING_FORMAT_VERSION = "nomic-search-prefix-v1"

_CODE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TOKENIZER_DIR = _CODE_ROOT / "data/external/modelweights/tokenizers/bert-base-uncased"


@dataclass(frozen=True)
class EmbeddingModelConfig:
    tokenizer_dir: str
    tokenizer_source: str
    document_prefix: str = ""
    query_prefix: str = ""
    chunk_token_limit: int = DEFAULT_CHUNK_TOKEN_LIMIT
    embed_context_limit: int = DEFAULT_EMBED_CONTEXT_LIMIT


def _normalize_model_name(model: str) -> str:
    name = (model or "").strip()
    if not name:
        return ""
    base = name.rsplit("/", 1)[-1]
    return base.split(":", 1)[0].lower()


_NOMIC_ALIASES = frozenset({"nomic-embed-text", "nomic-embed-text-v1", "nomic-embed-text-v1.5"})

EMBEDDING_MODEL_REGISTRY: dict[str, EmbeddingModelConfig] = {
    alias: EmbeddingModelConfig(
        tokenizer_dir="bert-base-uncased",
        tokenizer_source="bert-base-uncased (nomic-embed-text v1.5 uses this WordPiece vocab)",
        document_prefix="search_document: ",
        query_prefix="search_query: ",
    )
    for alias in _NOMIC_ALIASES
}


def embedding_model_config(model: str) -> EmbeddingModelConfig | None:
    key = _normalize_model_name(model)
    if not key:
        return None
    if key in EMBEDDING_MODEL_REGISTRY:
        return EMBEDDING_MODEL_REGISTRY[key]
    for alias, config in EMBEDDING_MODEL_REGISTRY.items():
        if key.startswith(alias):
            return config
    return None


_configured_tokenizer_root: Path | None = None


def configure(tokenizer_root_path: Path | str | None = None) -> None:
    global _configured_tokenizer_root
    _configured_tokenizer_root = Path(tokenizer_root_path).expanduser().resolve() if tokenizer_root_path else None


def tokenizer_root() -> Path:
    if _configured_tokenizer_root is not None:
        return _configured_tokenizer_root
    return (_CODE_ROOT / "data/external/modelweights/tokenizers").resolve()


def tokenizer_path(model: str) -> Path | None:
    config = embedding_model_config(model)
    if config is None:
        return None
    return tokenizer_root() / config.tokenizer_dir


def _tokenizer_files_present(path: Path) -> bool:
    required = ("vocab.txt", "tokenizer.json", "tokenizer_config.json")
    return path.is_dir() and all((path / name).is_file() for name in required)


def _conservative_token_estimate(text: str) -> int:
    return (len(text.encode("utf-8")) + 3) // 4


class _ConservativeTokenizer:
    max_tokens: int

    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens

    def count_tokens(self, text: str) -> int:
        return _conservative_token_estimate(text)

    def get_max_tokens(self) -> int:
        return self.max_tokens


@lru_cache(maxsize=8)
def _load_hf_tokenizer(path: str, max_tokens: int):
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

    return HuggingFaceTokenizer.from_pretrained(
        path,
        max_tokens=max_tokens,
        local_files_only=True,
    )


@lru_cache(maxsize=8)
def _load_transformers_tokenizer(path: str):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(path, local_files_only=True)


def chunk_tokenizer(
    embedding_model: str,
    *,
    chunk_token_limit: int = DEFAULT_CHUNK_TOKEN_LIMIT,
) -> tuple[Any, list[str]]:
    """Return a HybridChunker-compatible tokenizer and any warnings."""
    warnings: list[str] = []
    config = embedding_model_config(embedding_model)
    if config is None:
        warnings.append(
            f"Unknown embedding model {embedding_model!r}; using an approximate byte-based token estimate "
            "that cannot guarantee the model's token limit."
        )
        return _ConservativeTokenizer(chunk_token_limit), warnings

    path = tokenizer_root() / config.tokenizer_dir
    if not _tokenizer_files_present(path):
        warnings.append(
            f"Embedding tokenizer files missing at {path}; run `make embedding-tokenizer`. "
            "Using an approximate byte-based token estimate that cannot guarantee the model's token limit."
        )
        return _ConservativeTokenizer(chunk_token_limit), warnings

    try:
        probe = _load_transformers_tokenizer(str(path))
        prefix_tokens = len(probe.tokenize(config.document_prefix))
        # Reserve prefix tokens and BERT [CLS]/[SEP] overhead for the eventual embed call.
        chunk_budget = max(16, chunk_token_limit - prefix_tokens - 2)
        return _load_hf_tokenizer(str(path), chunk_budget), warnings
    except Exception as exc:  # noqa: BLE001 - tokenizer libraries raise arbitrary types; degrade with a warning
        warnings.append(
            f"Could not load offline tokenizer from {path} ({type(exc).__name__}: {exc}); "
            "using an approximate byte-based token estimate that cannot guarantee the model's token limit."
        )
        return _ConservativeTokenizer(chunk_token_limit), warnings


def embedding_prefix(model: str, role: EmbedRole) -> str:
    config = embedding_model_config(model)
    if config is None:
        return ""
    return config.document_prefix if role == "document" else config.query_prefix


def format_for_embedding(text: str, model: str, *, role: EmbedRole) -> str:
    prefix = embedding_prefix(model, role)
    if prefix and not text.startswith(prefix):
        return f"{prefix}{text}"
    return text


def count_embedding_tokens(text: str, model: str, *, role: EmbedRole | None = None) -> int:
    """Count tokens the way Ollama reports via prompt_eval_count (with special tokens)."""
    if role is not None:
        text = format_for_embedding(text, model, role=role)
    config = embedding_model_config(model)
    path = tokenizer_path(model) if config else None
    if config and path and _tokenizer_files_present(path):
        tokenizer = _load_transformers_tokenizer(str(path))
        return len(tokenizer.encode(text, add_special_tokens=True))
    return _conservative_token_estimate(text)


def count_with_chunk_tokenizer(
    text: str,
    model: str,
    tokenizer: Any,
    *,
    role: EmbedRole = "document",
) -> int:
    """Count the full embedding input using the tokenizer resolved for this ingest."""
    formatted = format_for_embedding(text, model, role=role)
    get_tokenizer = getattr(tokenizer, "get_tokenizer", None)
    if get_tokenizer is not None:
        return len(get_tokenizer().encode(formatted, add_special_tokens=True))
    return tokenizer.count_tokens(formatted)


def chunk_embed_token_limit(model: str) -> int:
    config = embedding_model_config(model)
    return config.chunk_token_limit if config else DEFAULT_CHUNK_TOKEN_LIMIT


def embed_context_limit(model: str) -> int:
    config = embedding_model_config(model)
    return config.embed_context_limit if config else DEFAULT_EMBED_CONTEXT_LIMIT


def embedding_index_key(model: str) -> str:
    """Identity stored with vectors; differs whenever query/document formatting differs."""
    if not model or not (embedding_prefix(model, "document") or embedding_prefix(model, "query")):
        return model
    return f"{model}#{EMBEDDING_FORMAT_VERSION}"


def embedding_format_metadata(model: str) -> dict[str, Any] | None:
    config = embedding_model_config(model)
    if config is None or not (config.document_prefix or config.query_prefix):
        return None
    return {
        "version": EMBEDDING_FORMAT_VERSION,
        "document_prefix": config.document_prefix,
        "query_prefix": config.query_prefix,
        "chunk_token_limit": config.chunk_token_limit,
        "tokenizer": config.tokenizer_dir,
        "tokenizer_source": config.tokenizer_source,
    }


def oversize_embed_error(model: str, token_count: int, limit: int) -> str:
    return (
        f"Embedding input for {model!r} is {token_count} tokens, exceeding the "
        f"{limit}-token context limit. Re-chunk the document or choose a smaller chunk limit."
    )


def normalize_ollama_embed_error(model: str, status_code: int, body: dict[str, Any] | str) -> str:
    message = body.get("error", body) if isinstance(body, dict) else str(body)
    text = str(message)
    if status_code == 400 and re.search(r"exceeds the context length", text, re.I):
        limit = embed_context_limit(model)
        return oversize_embed_error(model, limit + 1, limit)
    if status_code == 400:
        return f"Ollama rejected the embedding request for {model!r}: {text}"
    return f"Ollama embed failed ({status_code}): {text}"
