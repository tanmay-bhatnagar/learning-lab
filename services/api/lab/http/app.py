"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from lab.config import AppConfig, load_config
from lab.errors import DomainError
from lab.http import chat, files, settings, topics
from lab.http.deps import AppDeps
from lab.http.middleware import UploadBodyLimit, browser_boundary_middleware
from lab.storage import Store


def create_app(
    root: Path | str | None = None,
    settings_path: Path | str | None = None,
    model_backend: Any | None = None,
    converter: Any | None = None,
    structured_parser: Any | None = None,
    retriever: Any | None = None,
    max_upload_bytes: int | None = None,
    parser_map: dict[str, Any] | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    """Build the Learning Lab API; explicit arguments override environment defaults."""
    loaded = config or load_config(
        learning_root=Path(root) if root is not None else None,
        settings_path=Path(settings_path) if settings_path is not None else None,
        max_upload_bytes=max_upload_bytes,
    )
    import lab.docling_pipeline as docling_pipeline
    import lab.embedding_config as embedding_config
    import lab.models as models

    models.configure(loaded.ollama_base_url)
    docling_pipeline.configure(loaded.docling_artifacts_path)
    embedding_config.configure(loaded.embedding_tokenizer_root)

    store = Store(loaded.learning_root, loaded.settings_path)
    deps = AppDeps(
        store=store,
        config=loaded,
        model_backend=model_backend,
        structured_parser=structured_parser,
        retriever=retriever,
    )
    if parser_map is not None:
        deps.parser_map = parser_map
    elif converter is not None:
        deps.parser_map = {
            "markitdown": converter,
            "anydoc": converter,
            "docling": converter,
        }

    app = FastAPI(title="Learning Lab")
    app.state.deps = deps

    @app.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
    limit = loaded.max_upload_bytes
    app.add_middleware(UploadBodyLimit, limit=limit + 65536)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    app.middleware("http")(browser_boundary_middleware(origins, limit))

    app.include_router(settings.router(deps))
    app.include_router(topics.router(deps))
    app.include_router(files.router(deps))
    app.include_router(chat.router(deps))

    return app
