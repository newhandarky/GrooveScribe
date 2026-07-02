from fastapi import APIRouter

from app.api.routes import health, runtime, transcriptions

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(runtime.router)
api_router.include_router(transcriptions.router)
