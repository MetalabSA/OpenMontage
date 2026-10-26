"""Cabina Studio API application factory."""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

    import asyncio
    from contextlib import suppress

    from api.services.alerts import ops_scheduler
    from api.services.backups import backup_scheduler
    from api.watcher import watch_projects

    watcher = asyncio.create_task(watch_projects())
    scheduler = asyncio.create_task(backup_scheduler())
    ops = asyncio.create_task(ops_scheduler())
    try:
        yield
    finally:
        for task in (watcher, scheduler, ops):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


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
        import time as _time

        from api.telemetry import http_stats, log_request

        started = _time.perf_counter()
        request.state.request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:16]}"
        response = await call_next(request)
        duration_ms = (_time.perf_counter() - started) * 1000
        http_stats.record(response.status_code, duration_ms)
        if request.url.path.startswith("/api/"):
            log_request(request.state.request_id, request.method, request.url.path, response.status_code, duration_ms)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-API-Version"] = "1"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob:; media-src 'self' blob:; "
            "connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'"
        )
        if request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            from api.ratelimit import limiter

            client = request.client.host if request.client else "unknown"
            if path == "/api/auth/login":
                allowed, remaining, reset = limiter.hit(f"login:{client}", 10, 900)
            else:
                allowed, remaining, reset = limiter.hit(f"api:{client}", 300, 60)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"error": {"code": "rate_limited", "message": "Too many requests", "details": {}, "request_id": getattr(request.state, "request_id", None)}},
                    headers={"Retry-After": str(max(1, reset - int(__import__("time").time())))},
                )
            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset)
            return response
        return await call_next(request)

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(Exception, unhandled_handler)
    app.include_router(router)

    web_dist = config.ROOT / "web" / "dist"
    if web_dist.is_dir():
        assets = web_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="spa-assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (web_dist / path).resolve()
            if path and candidate.is_file() and web_dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(web_dist / "index.html")

    return app


app = create_app()
