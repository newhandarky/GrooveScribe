from fastapi import FastAPI

from app.api.error_handlers import register_exception_handlers
from app.api.routes.health import router as health_router
from app.api.routes.internal import router as internal_router
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.services.local_job_recovery import build_local_job_recovery_lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, lifespan=build_local_job_recovery_lifespan(settings))
    register_exception_handlers(app)

    app.include_router(health_router)
    if settings.internal_api_enabled:
        app.include_router(internal_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
