import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import logger
from app.core.qdrant import ensure_brand_embeddings_collection


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    if settings.langsmith_api_key:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)
        logger.info("langsmith_tracing_enabled", project=settings.langsmith_project)
    else:
        logger.info("langsmith_tracing_disabled")

    try:
        await ensure_brand_embeddings_collection()
    except Exception as exc:
        logger.warning("qdrant_init_failed", error=str(exc))

    yield


app = FastAPI(title="DistroAgent", version="0.1.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS — allow all origins in dev; tighten in production via env var
# ---------------------------------------------------------------------------

_origins = [o.strip() for o in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(api_router)
app.include_router(health_router)
