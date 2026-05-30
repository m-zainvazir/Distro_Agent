from fastapi import FastAPI

from app.api.v1.brands import router as brands_router
from app.api.v1.scoring import router as scoring_router

app = FastAPI(title="DistroAgent", version="0.1.0")

app.include_router(brands_router, prefix="/api/v1")
app.include_router(scoring_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
