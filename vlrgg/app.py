"""The FastAPI application: routes, error bodies, rate limits."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from vlrgg import __version__
from vlrgg.api import router
from vlrgg.errors import ApiError
from vlrgg.net.client import upstream
from vlrgg.throttle import Throttle

logger = logging.getLogger("vlrgg")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await upstream().close()


def create_app(*, throttle: bool = True) -> FastAPI:
    app = FastAPI(
        title="vlr-gg-api",
        version=__version__,
        description="Unofficial REST API for vlr.gg: matches, events, teams, players, rankings and stats.",
        docs_url="/",
        redoc_url=None,
        lifespan=lifespan,
    )
    if throttle:
        app.add_middleware(Throttle)
    app.include_router(router)

    @app.get("/version", tags=["Meta"], summary="API version")
    async def version():
        return {"data": {"version": __version__}}

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        if exc.status >= 500:
            logger.warning("%s %s -> %s: %s", request.method, request.url.path, exc.status, exc.message)
        return _error(exc.status, exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        problems = ["{}: {}".format(".".join(str(p) for p in error["loc"]), error["msg"]) for error in exc.errors()]
        return _error(400, "; ".join(problems))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = "Not found" if exc.status_code == 404 else str(exc.detail)
        return _error(exc.status_code, message)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error(502, "Could not read the vlr.gg page")

    return app


app = create_app()
