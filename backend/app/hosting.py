"""Single-service hosting helpers: password protection and serving the built UI.

Both are off unless configured, so local development and docker-compose are unchanged.
"""
from __future__ import annotations

import base64
import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles

OPEN_PATHS = {"/api/health"}  # the host's health check must work without the password


class DemoPasswordMiddleware(BaseHTTPMiddleware):
    """HTTP Basic auth with one shared password. The browser shows its own sign-in prompt and then
    sends the credentials with every request, including the UI's API calls. Any username works."""

    def __init__(self, app, password: str):
        super().__init__(app)
        self._password = password.encode()

    async def dispatch(self, request, call_next):
        if request.url.path in OPEN_PATHS or self._authorised(request.headers.get("authorization")):
            return await call_next(request)
        return Response("Sign in required", status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="Valley Medical POC", charset="UTF-8"'})

    def _authorised(self, header: str | None) -> bool:
        if not header or not header.lower().startswith("basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return False
        _, _, password = decoded.partition(":")
        return secrets.compare_digest(password.encode(), self._password)


class SPAStaticFiles(StaticFiles):
    """Serves the React build; unknown non-API paths return index.html so client-side routes work."""

    async def get_response(self, path: str, scope):
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"error": "not_found", "message": "Not found"}, status_code=404)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return FileResponse(Path(self.directory) / "index.html")
            raise


def configure_hosting(app: FastAPI, *, static_dir: Path | None, demo_password: str | None) -> None:
    if demo_password:
        app.add_middleware(DemoPasswordMiddleware, password=demo_password)
    if static_dir and (Path(static_dir) / "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=str(static_dir), html=True), name="ui")
