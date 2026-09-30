"""Settings and model listing HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter

from lab.http.deps import AppDeps
from lab.http.schemas import Settings
from lab.storage import checked, read_json, write_json


def router(deps: AppDeps) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/health")
    def health():
        return {"status": "ok"}

    @routes.get("/api/settings")
    def get_settings():
        return Settings(**read_json(deps.store.settings, {})).model_dump()

    @routes.put("/api/settings")
    def set_settings(body: Settings):
        checked(deps.store.settings.parent).mkdir(parents=True, exist_ok=True)
        write_json(deps.store.settings, body.model_dump())
        return body.model_dump()

    @routes.get("/api/models")
    async def models():
        try:
            return await deps.backend().list_models()
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            return {
                "models": [],
                "error": f"Model service unavailable ({type(exc).__name__}); check the local model service and backend dependencies.",
            }

    return routes
