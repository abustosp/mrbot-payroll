from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text

from app.api import (
    agreements,
    auth,
    companies,
    concepts,
    employees,
    exports,
    formulas,
    imports,
    normative_packages,
    payroll_runs,
    reports,
    settlements,
)
from app.config import get_settings
from app.database.session import engine
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
        imports.router,
        normative_packages.router,
        reports.router,
        settlements.router,
    ):
        application.include_router(router, prefix="/api/v1")
    if ai_router is not None:
        application.include_router(ai_router, prefix="/api/v1")
    application.include_router(web_router)

    # B-50: sin esto, una DB sin migrar responde 500 en texto plano. Los
    # HTTPException conservan su handler específico; esto solo cubre fallos
    # no previstos con una página de recuperación.
    @application.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> HTMLResponse:
        try:
            health_url = str(request.url_for("health_page"))
        except Exception:
            health_url = "/salud"
        return HTMLResponse(
            status_code=500,
            content=(
                "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
                "<title>Error interno · Payroll Argentina</title></head><body>"
                "<h1>No se pudo completar la operación</h1>"
                "<p>La base de datos puede estar sin migrar o bloqueada. "
                "Ejecutá <code>alembic upgrade head</code> y reintentá.</p>"
                f"<p><a href=\"{health_url}\">Ver estado del sistema</a></p>"
                "</body></html>"
            ),
        )

    @application.get("/health", tags=["system"], response_model=None)
    def health() -> dict[str, str] | JSONResponse:
        # B-24: el healthcheck de Docker usa esta URL; sin SELECT 1 un
        # contenedor sin base figura sano.
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "environment": settings.environment},
            )
        return {"status": "ok", "environment": settings.environment}

    return application


app = create_app()
