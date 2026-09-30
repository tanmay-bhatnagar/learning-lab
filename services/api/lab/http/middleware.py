"""ASGI middleware used by the HTTP layer."""

from __future__ import annotations

from anyio import CancelScope
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


class UploadBodyLimit:
    """Bound multipart bytes before Starlette parses or spools the upload."""

    def __init__(self, app, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit if scope.get("path", "").endswith("/files") else 2 * 1024 * 1024
        used = 0

        async def bounded_receive():
            nonlocal used
            message = await receive()
            if message["type"] == "http.request":
                used += len(message.get("body", b""))
                if used > limit:
                    raise HTTPException(413, "Request body exceeds the configured upload limit.")
            return message

        await self.app(scope, bounded_receive, send)


class FinalizedStreamingResponse(StreamingResponse):
    """Run `on_close` once however the response ends, including before streaming starts."""

    def __init__(self, content, *, on_close, **kwargs) -> None:
        super().__init__(content, **kwargs)
        self.on_close = on_close

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with CancelScope(shield=True):
                try:
                    await self.body_iterator.aclose()
                finally:
                    await self.on_close()


def browser_boundary_middleware(origins: list[str], upload_limit: int):
    async def browser_boundary(request: Request, call_next):
        if request.headers.get("origin") and request.headers["origin"] not in origins:
            return JSONResponse({"detail": "Browser origin is not allowed."}, status_code=403)
        if request.method == "POST" and request.url.path.endswith("/files"):
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > upload_limit + 65536):
                return JSONResponse(
                    {"detail": f"Upload exceeds {upload_limit} byte PDF limit."},
                    status_code=413,
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return browser_boundary
