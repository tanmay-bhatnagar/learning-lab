"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from lab.config import AppConfig, load_config
from lab.contracts import ModelGateway
from lab.errors import DomainError
from lab.models import OllamaGateway
from lab.storage import Store
from lab.web import chat, files, settings, topics
from lab.web.deps import AppDeps, ParserFn, RetrieverFn, StructuredParserFn
from lab.web.middleware import UploadBodyLimit, browser_boundary_middleware


def create_app(
    root: Path | str | None = None,
    settings_path: Path | str | None = None,
    model_backend: ModelGateway | None = None,
    structured_parser: StructuredParserFn | None = None,
    retriever: RetrieverFn | None = None,
    max_upload_bytes: int | None = None,
    parser_map: dict[str, ParserFn] | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    """Build the Learning Lab API; explicit arguments override environment defaults."""
    loaded = config or load_config(
        learning_root=Path(root) if root is not None else None,
        settings_path=Path(settings_path) if settings_path is not None else None,
        max_upload_bytes=max_upload_bytes,
    )
    store = Store(loaded.learning_root, loaded.settings_path)
    gateway = model_backend or OllamaGateway(loaded.ollama_base_url)
    deps = AppDeps(
        store=store,
        config=loaded,
        model_backend=gateway,
        structured_parser=structured_parser,
        retriever=retriever,
        parser_map=parser_map,
    )

    app = FastAPI(title="Learning Lab")
    app.state.deps = deps

    @app.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
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
