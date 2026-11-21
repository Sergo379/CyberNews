import logging
import re
from contextlib import asynccontextmanager
from collections.abc import Callable
from http import HTTPStatus
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError, TimeoutError
from starlette.exceptions import HTTPException

from .config import Settings
from .database import Database
from .logs import request_id

logger = logging.getLogger("cybernews.http")
valid_request_id = re.compile(r"[a-zA-Z0-9._-]{1,128}")


def create_application(
    title: str, settings: Settings, router: APIRouter, public_prefix: str,
    *, dependency_check: Callable[[], bool] | None = None, startup: Callable[[], None] | None = None,
    shutdown: Callable[[], None] | None = None, dependency_name: str = "auth",
) -> FastAPI:
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            if startup is not None:
                startup()
            yield
        finally:
            try:
                if shutdown is not None:
                    shutdown()
            finally:
                database.engine.dispose()

    app = FastAPI(
        title=title,
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        servers=[{"url": public_prefix}, {"url": "/"}],
    )
    app.state.database = database
    default_openapi = app.openapi

    def openapi():
        schema = default_openapi()
        for methods in schema["paths"].values():
            for operation in methods.values():
                if not isinstance(operation, dict):
                    continue
                schemes = {name for entry in operation.get("security", []) for name in entry}
                if schemes == {"AccessToken", "AdminSession"}:
                    operation["security"] = [{"AccessToken": [], "AdminSession": []}]
        return schema

    app.openapi = openapi

    @app.get("/docs", include_in_schema=False)
    def docs():
        return get_swagger_ui_html(openapi_url="./openapi.json", title=f"{title} API")

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        supplied_id = request.headers.get("X-Request-ID", "")
        identifier = supplied_id if valid_request_id.fullmatch(supplied_id) else uuid4().hex
        token = request_id.set(identifier)
        started_at = perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                logger.error("Unhandled request error", extra={"error_type": type(exc).__name__})
                response = JSONResponse({"detail": "Internal server error"}, status_code=500)

            response.headers["X-Request-ID"] = identifier
            logger.info(
                "HTTP request completed",
                extra={
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            return response
        finally:
            request_id.reset(token)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        try:
            detail = HTTPStatus(exc.status_code).phrase
        except ValueError:
            detail = "HTTP request failed"
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError):
        return JSONResponse({"detail": "Request validation failed"}, status_code=422)

    async def database_unavailable(_: Request, exc: Exception):
        logger.warning("Database unavailable", extra={"error_type": type(exc).__name__})
        return JSONResponse({"detail": "Service Unavailable"}, status_code=503)

    for error in (OperationalError, InterfaceError, TimeoutError):
        app.add_exception_handler(error, database_unavailable)

    @router.get("/health", tags=["operations"])
    def health():
        return {"service": settings.service_name, "status": "ok"}

    @router.get("/ready", tags=["operations"], responses={503: {"description": "Database unavailable"}})
    def ready():
        try:
            database.check()
        except SQLAlchemyError as exc:
            logger.warning("Database readiness check failed", extra={"error_type": type(exc).__name__})
            return JSONResponse(
                {"service": settings.service_name, "status": "unavailable", "database": "unavailable"},
                status_code=503,
            )
        if dependency_check is not None and not dependency_check():
            return JSONResponse(
                {"service": settings.service_name, "status": "unavailable", "database": "ok", dependency_name: "unavailable"},
                status_code=503,
            )
        return {"service": settings.service_name, "status": "ready", "database": "ok"}

    app.include_router(router)
    return app
