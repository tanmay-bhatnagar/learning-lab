"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from functools import partial

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from lab.config import AppConfig, load_config
from lab.contracts import ModelGateway
from lab.errors import DomainError
from lab.models import OllamaGateway
from lab.profile_store import ProfileStore
from lab.storage import Store
from lab.profile_parse import parse_profile_pdf
from lab.web import (
    chat,
    conversations,
    conversation_profile,
    document_map_summaries,
    document_maps,
    files,
    profile,
    prerequisites,
    prerequisite_imports,
    settings,
    summary_imports,
    topics,
)
from lab.web.deps import AppDeps, ParserFn, ProfileParserFn, RetrieverFn, StructuredParserFn
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
    runtime_policy_path: Path | None = None,
    profile_root: Path | None = None,
    profile_parser: ProfileParserFn | None = None,
) -> FastAPI:
    """Build the Learning Lab API; explicit arguments override environment defaults."""
    loaded = config or load_config(
        learning_root=Path(root) if root is not None else None,
        settings_path=Path(settings_path) if settings_path is not None else None,
        max_upload_bytes=max_upload_bytes,
        runtime_policy_path=runtime_policy_path,
        profile_root=profile_root,
    )
    store = Store(loaded.learning_root, loaded.settings_path)
    profile_store = ProfileStore(loaded.profile_root)
    selected_profile_parser = profile_parser or partial(
        parse_profile_pdf,
        parser_map=parser_map,
        artifacts_path=loaded.docling_artifacts_path,
    )
    gateway = model_backend or OllamaGateway(loaded.ollama_base_url)
    deps = AppDeps(
        store=store,
        profile_store=profile_store,
        profile_parser=selected_profile_parser,
        config=loaded,
        model_backend=gateway,
        structured_parser=structured_parser,
        retriever=retriever,
        parser_map=parser_map,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await deps.active_runs.cancel_all()

    app = FastAPI(title="Learning Lab", lifespan=lifespan)
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
    app.include_router(profile.router(deps))
    app.include_router(conversation_profile.router(deps))
    app.include_router(prerequisites.router(deps))
    app.include_router(prerequisite_imports.router(deps))
    app.include_router(topics.router(deps))
    app.include_router(files.router(deps))
    app.include_router(document_maps.router(deps))
    app.include_router(document_map_summaries.router(deps))
    app.include_router(summary_imports.router(deps))
    app.include_router(chat.router(deps))
    app.include_router(conversations.router(deps))

    return app
