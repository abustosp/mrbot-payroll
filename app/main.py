from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agreements,
    auth,
    companies,
    concepts,
    employees,
    exports,
    formulas,
    payroll_runs,
)
from app.config import get_settings
from app.web.routes import router as web_router
from app.web.sql_data_source import SqlAlchemyDataSource

ai_router: APIRouter | None
try:
    from app.api.ai import router as ai_router
except (ImportError, AttributeError):
    ai_router = None


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Motor determinista de liquidacion de sueldos con IA supervisada.",
    )
    if settings.web_data_source == "sql":
        application.state.payroll_data_source = SqlAlchemyDataSource()
    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    for router in (
        auth.router,
        companies.router,
        employees.router,
        agreements.router,
        concepts.router,
        formulas.router,
        payroll_runs.router,
        exports.router,
    ):
        application.include_router(router, prefix="/api/v1")
    if ai_router is not None:
        application.include_router(ai_router, prefix="/api/v1")
    application.include_router(web_router)

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    return application


app = create_app()

