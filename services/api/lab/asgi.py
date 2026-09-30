"""ASGI entry point without import-time side effects."""

from lab.http.app import create_app


def app_factory():
    return create_app()


app = app_factory()
