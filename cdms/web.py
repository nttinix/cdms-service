import secrets
from contextlib import asynccontextmanager
from typing import Annotated

import psycopg
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from psycopg_pool import PoolTimeout

from cdms.store import Store, VersionConflict


def base_app(title, settings):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(settings.database_url)
        yield
        app.state.store.close()

    app = FastAPI(title=title, version="0.1.0", lifespan=lifespan)
    key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def authorize(key: Annotated[str | None, Security(key_header)] = None):
        if not key or not secrets.compare_digest(key, settings.api_token):
            raise HTTPException(403, "Invalid API key")

    @app.exception_handler(VersionConflict)
    async def conflict(request: Request, error: VersionConflict):
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "message": str(error),
                    "productId": error.product_id,
                    "sourceVersion": error.version,
                }
            },
        )

    async def unavailable(request: Request, error):
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable"},
            headers={"Retry-After": "2"},
        )

    for error_type in (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout):
        app.add_exception_handler(error_type, unavailable)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready(request: Request):
        request.app.state.store.db.ready()
        return {"status": "ready"}

    return app, authorize
