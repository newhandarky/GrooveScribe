from fastapi import APIRouter

from app.api.routes import health, local_data, runtime, transcriptions

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(runtime.router)
api_router.include_router(transcriptions.router)
api_router.include_router(local_data.router)
