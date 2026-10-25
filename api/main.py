"""Cabina Studio API application factory."""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from api import config, db
from api.errors import ApiError, api_error_handler, unhandled_handler, validation_handler
from api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db.init_db()
    from api import security

    conn = db.connect()
    try:
        security.ensure_admin(conn)
    finally:
        conn.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cabina Studio API",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in os.environ.get("OM_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:16]}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-API-Version"] = "1"
        return response

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(Exception, unhandled_handler)
    app.include_router(router)
    return app


app = create_app()
