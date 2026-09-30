"""Settings and model listing HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter

from lab.web.deps import AppDeps
from lab.web.schemas import Settings
from lab.web.settings_store import load_settings
from lab.storage import checked, write_json


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/health")
    def health():
        return {"status": "ok"}

    @routes.get("/api/settings")
    def get_settings():
        return load_settings(deps.store).model_dump()

    @routes.put("/api/settings")
    def set_settings(body: Settings):
        checked(deps.store.settings.parent).mkdir(parents=True, exist_ok=True)
        write_json(deps.store.settings, body.model_dump())
        return body.model_dump()

    @routes.get("/api/models")
    async def models():
        return await deps.model_backend.list_models()

    return routes
