"""FastAPI entrypoint: `uvicorn app.main:create_app --factory`."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, billing, patients
from app.container import Container, build_container
from app.errors import DomainError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(container: Container | None = None) -> FastAPI:
    container = container or build_container()
    app = FastAPI(title="Valley Medical AI Platform POC", version="0.1.0",
                  description="Proof of concept. Synthetic data only. Read-only integrations.")
    app.state.container = container
    app.add_middleware(CORSMiddleware, allow_origins=container.settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Demo-User", "X-Demo-Role"])

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception):
        logging.getLogger("app").exception("Unhandled error")
        # Never echo internal details (which could include data) to the client.
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": "Something went wrong. The error was logged."})

    app.include_router(admin.router)
    app.include_router(patients.router)
    app.include_router(billing.router)
    return app

