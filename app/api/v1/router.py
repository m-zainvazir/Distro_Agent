from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.brands import router as brands_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.endpoints.discovery import router as discovery_router
from app.api.v1.scoring import router as scoring_router
from app.api.v1.insights import router as insights_router
from app.api.v1.webhooks import router as webhooks_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(brands_router)
api_router.include_router(campaigns_router)
api_router.include_router(insights_router)
api_router.include_router(scoring_router)
api_router.include_router(discovery_router)
api_router.include_router(webhooks_router)
