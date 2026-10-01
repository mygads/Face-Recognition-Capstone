from __future__ import annotations

from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityConfigurationError(ValueError):
    """Raised when HTTP security settings are malformed or unsafe."""


def parse_cors_allowed_origins(raw: str | None) -> tuple[str, ...]:
    if not raw or not raw.strip():
        return ()
    origins: list[str] = []
    for item in raw.split(","):
        origin = item.strip().rstrip("/")
        if not origin or origin == "*":
            raise SecurityConfigurationError(
                "CORS origins must be explicit HTTP(S) origins, not wildcards."
            )
        try:
            parsed = urlsplit(origin)
            _ = parsed.port
        except ValueError as exc:
            raise SecurityConfigurationError("A CORS origin is malformed.") from exc
        hostname = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in parsed.netloc
        ):
            raise SecurityConfigurationError(
                "Each CORS setting must be a single origin without a path."
            )
        if parsed.scheme == "http" and hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise SecurityConfigurationError("Non-local CORS origins must use HTTPS.")
        if origin not in origins:
            origins.append(origin)
    return tuple(origins)


def add_restrictive_cors(app: Starlette, allowed_origins: tuple[str, ...]) -> None:
    if not allowed_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Device-ID"],
        expose_headers=["Retry-After"],
        max_age=600,
    )


def configure_multipart_memory_only(max_request_bytes: int) -> None:
    """Keep accepted multipart files in memory instead of temp files on disk."""
    from starlette.formparsers import MultiPartParser

    MultiPartParser.spool_max_size = max_request_bytes


class RequestBodyTooLarge(Exception):
    """Internal signal used to stop parsing an oversized request body."""


class RequestBodySizeLimitMiddleware:
    """Bound bodies before multipart parsing, without buffering or logging them."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive.")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", [])
                if key.lower() == b"content-length"
            ),
            None,
        )
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._send_error(scope, receive, send, 400, "bad_request")
                return
            if declared_length < 0:
                await self._send_error(scope, receive, send, 400, "bad_request")
                return
            if declared_length > self.max_bytes:
                await self._send_error(scope, receive, send, 413, "file_too_large")
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if not response_started:
                await self._send_error(scope, receive, send, 413, "file_too_large")

    async def _send_error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        code: str,
    ) -> None:
        message = (
            "The uploaded file exceeds the allowed size."
            if status_code == 413
            else "The request could not be processed."
        )
        response = JSONResponse(
            status_code=status_code,
            content={"error": {"code": code, "message": message}},
        )
        await response(scope, receive, send)
