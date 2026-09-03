import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from .audit import configure_logging
from .config import settings
from .routers import auth, captures, classes, observations, review, students

configure_logging()
logger = logging.getLogger("muendlich")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ai_provider == "stub":
        logger.warning(
            "AI_PROVIDER=stub — sentiment is a keyword heuristic, not a model. "
            "Do not use this against real classes."
        )
    if settings.anonymize_enabled:
        # Fail fast rather than silently degrading to gazetteer-only coverage on
        # the first dictation.
        from .ai.anonymize import load_ner

        load_ner(required=settings.is_production)
    if not settings.is_production:
        logger.warning("ENVIRONMENT=%s — set ENVIRONMENT=production when deploying", settings.environment)
    yield


app = FastAPI(
    title="muendlich API",
    version="0.1.0",
    lifespan=lifespan,
    # The API surface is not a secret, but there's no reason to publish it.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    # Explicit lists rather than "*": with allow_credentials the wildcard is
    # both riskier and, per spec, not actually honoured by browsers.
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def no_store_api_responses(request: Request, call_next):
    """Keep pupil data out of shared and on-disk HTTP caches.

    Static assets are content-hashed and hold no personal data, so the PWA's
    own caching is left alone.
    """
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
    return response


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """A constraint violation is a bad request, not a server fault."""
    logger.warning("IntegrityError on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "Die Änderung verletzt eine Datenbank-Einschränkung."},
    )


app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(students.router)
app.include_router(captures.router)
app.include_router(observations.router)
app.include_router(review.router)


@app.get("/api/health")
def health() -> dict:
    """Liveness only. Configuration details are not public information."""
    return {"status": "ok"}
