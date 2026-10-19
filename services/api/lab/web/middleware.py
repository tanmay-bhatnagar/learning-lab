"""ASGI middleware used by the HTTP layer."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from anyio import CancelScope, create_task_group
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UploadBodyLimit:
    """Bound multipart bytes before Starlette parses or spools the upload."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit if scope.get("path", "").endswith("/files") else 2 * 1024 * 1024
        used = 0

        async def bounded_receive() -> Message:
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

    def __init__(
        self,
        content: AsyncIterator[str],
        *,
        on_close: Callable[[], Awaitable[None]],
        **kwargs: Any,
    ) -> None:
        super().__init__(content, **kwargs)
        self.on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            spec_version = tuple(map(int, scope.get("asgi", {}).get("spec_version", "2.0").split(".")))
            if spec_version < (2, 4):
                await super().__call__(scope, receive, send)
            else:
                await self._stream_with_disconnect_listener(receive, send)
        finally:
            with CancelScope(shield=True):
                try:
                    await self.body_iterator.aclose()
                finally:
                    await self.on_close()

    async def _stream_with_disconnect_listener(self, receive: Receive, send: Send) -> None:
        completed = False
        try:
            async with create_task_group() as tasks:

                async def stream_response() -> None:
                    nonlocal completed
                    try:
                        await self.stream_response(send)
                    except OSError as exc:
                        raise ClientDisconnect() from exc
                    else:
                        completed = True
                    finally:
                        tasks.cancel_scope.cancel()

                async def listen_for_disconnect() -> None:
                    await self.listen_for_disconnect(receive)
                    tasks.cancel_scope.cancel()

                tasks.start_soon(stream_response)
                tasks.start_soon(listen_for_disconnect)
        except BaseExceptionGroup as group:
            if len(group.exceptions) != 1:
                raise
            raise group.exceptions[0] from group

        if completed and self.background is not None:
            await self.background()


def browser_boundary_middleware(
    origins: list[str], upload_limit: int
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def browser_boundary(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
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
