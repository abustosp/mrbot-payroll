from fastapi import APIRouter, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import text

from app.api import (
    agreements,
    auth,
    companies,
    concepts,
    contracts,
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
    # V2-14: cada origen CORS permitido es de plena confianza CSRF cuando hay
    # cookies (allow_credentials). Mantener la lista vacia por defecto; solo
    # abrir un frontend propio por HTTPS y enviar X-CSRF-Token en POST/PUT/
    # PATCH/DELETE de la API con cookie.
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
        contracts.router,
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

    # B-50/PW-2/PW-5: sin esto, una DB sin migrar responde 500 en texto
    # plano. Los HTTPException conservan su handler especifico; esto solo
    # cubre fallos no previstos: JSON para /api/ (clientes e integraciones),
    # pagina HTML con enlace relativo a /salud solo para la web.
    @application.exception_handler(Exception)
    async def unhandled_error(
        request: Request, exc: Exception
    ) -> HTMLResponse | JSONResponse:
        # PW-5: enlace relativo; url_for absoluto rompe detras de un proxy.
        try:
            health_url = request.url_for("health_page").path
        except Exception:
            health_url = "/salud"
        # PW-2: la API JSON nunca debe recibir HTML en un 500.
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Error interno; la base puede estar sin migrar "
                    "o bloqueada. Ejecutá `alembic upgrade head` y reintentá."
                },
            )
        return HTMLResponse(
            status_code=500,
            content=(
                '<!doctype html><html lang="es"><head><meta charset="utf-8">'
                "<title>Error interno · Payroll Argentina</title></head><body>"
                "<h1>No se pudo completar la operación</h1>"
                "<p>La base de datos puede estar sin migrar o bloqueada. "
                "Ejecutá <code>alembic upgrade head</code> y reintentá.</p>"
                f'<p><a href="{health_url}">Ver estado del sistema</a></p>'
                "</body></html>"
            ),
        )

    # PW-4: 404 global coherente: JSON para /api/, pagina HTML para la web.
    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api/"):
            return await http_exception_handler(request, exc)
        if exc.status_code != 404:
            return await http_exception_handler(request, exc)
        return HTMLResponse(
            status_code=404,
            content=(
                '<!doctype html><html lang="es"><head><meta charset="utf-8">'
                "<title>Página no encontrada · Payroll Argentina</title></head>"
                "<body><h1>Página no encontrada</h1>"
                "<p>La ruta no existe en la interfaz web.</p>"
                '<p><a href="/">Volver al inicio</a> · '
                '<a href="/salud">Ver estado del sistema</a></p>'
                "</body></html>"
            ),
        )

    @application.get("/health", tags=["system"], response_model=None)
    def health() -> dict[str, str] | JSONResponse:
        # B-24/PW-1: el healthcheck de Docker usa esta URL. SELECT 1 solo
        # prueba la conexion: un sqlite vacio sin tablas responde ok aunque
        # nada que toque la DB funcione. Probar una tabla real (version de
        # migracion) y devolver 503 si falta.
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "environment": settings.environment},
            )
        return {"status": "ok", "environment": settings.environment}

    return application


app = create_app()
