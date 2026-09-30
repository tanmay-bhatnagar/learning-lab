"""ASGI entry point without import-time side effects."""

from fastapi import FastAPI

from lab.web.app import create_app


def create_app_factory() -> FastAPI:
    return create_app()
