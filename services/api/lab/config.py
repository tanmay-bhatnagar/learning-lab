"""Application configuration read once at the composition root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEARNING_ROOT = CODE_ROOT.parent / "Learning"
DEFAULT_STATE_ROOT = CODE_ROOT / ".local"
DEFAULT_SETTINGS_NAME = "settings.json"
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_DOCLING_ARTIFACTS_PATH = CODE_ROOT / "data" / "external" / "modelweights" / "docling"
DEFAULT_EMBEDDING_TOKENIZER_ROOT = CODE_ROOT / "data" / "external" / "modelweights" / "embedding-tokenizer"


@dataclass(frozen=True, slots=True)
class AppConfig:
    learning_root: Path
    state_root: Path
    settings_path: Path
    max_upload_bytes: int
    ollama_base_url: str
    docling_artifacts_path: Path
    embedding_tokenizer_root: Path


def load_config(
    *,
    learning_root: Path | None = None,
    settings_path: Path | None = None,
    max_upload_bytes: int | None = None,
    ollama_base_url: str | None = None,
    docling_artifacts_path: Path | None = None,
    embedding_tokenizer_root: Path | None = None,
) -> AppConfig:
    """Build config from explicit arguments with environment fallbacks."""
    state_root = Path(os.environ.get("LEARNING_LAB_STATE_ROOT", str(DEFAULT_STATE_ROOT))).expanduser()
    return AppConfig(
        learning_root=Path(
            learning_root
            if learning_root is not None
            else os.environ.get("LEARNING_LAB_ROOT", str(DEFAULT_LEARNING_ROOT))
        ).expanduser(),
        state_root=state_root,
        settings_path=Path(
            settings_path
            if settings_path is not None
            else os.environ.get(
                "LEARNING_LAB_SETTINGS",
                str(state_root / DEFAULT_SETTINGS_NAME),
            )
        ).expanduser(),
        max_upload_bytes=max_upload_bytes
        if max_upload_bytes is not None
        else int(os.environ.get("LEARNING_LAB_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)),
        ollama_base_url=(
            ollama_base_url
            if ollama_base_url is not None
            else os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        ).rstrip("/"),
        docling_artifacts_path=Path(
            docling_artifacts_path
            if docling_artifacts_path is not None
            else os.environ.get("DOCLING_ARTIFACTS_PATH", str(DEFAULT_DOCLING_ARTIFACTS_PATH))
        ).expanduser(),
        embedding_tokenizer_root=Path(
            embedding_tokenizer_root
            if embedding_tokenizer_root is not None
            else os.environ.get("EMBEDDING_TOKENIZER_ROOT", str(DEFAULT_EMBEDDING_TOKENIZER_ROOT))
        ).expanduser(),
    )
