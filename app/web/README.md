# Interfaz web

Implementación de la UI AdminLTE 4 con Jinja2 + HTMX y de la generación de
recibos PDF. La interfaz funciona sin CDN: el layout, las tablas, las tarjetas
y los formularios se estilan con `static/css/app.css`; Bootstrap/AdminLTE y
HTMX se cargan como mejora progresiva.

## Montaje

En `app/main.py`:

```python
from app.web.routes import router as web_router

application.include_router(web_router)
```

No hace falta montar `StaticFiles`: el CSS y el JavaScript locales se sirven
desde `GET /static/app.css` y `GET /static/app.js`. El router puede incluirse
con un prefijo (por ejemplo `prefix="/panel"`); las plantillas usan `url_for`
y respetan el prefijo.

`GET /health` sigue perteneciendo a la aplicación principal (JSON). El health
visual está en `GET /salud` y en el alias `GET /health/visual`.

## Rutas

| Ruta | Pantalla |
|---|---|
| `/login` | Ingreso con formulario HTML |
| `/logout` | Cierre de sesión (POST con CSRF) |
| `/` | Dashboard |
| `/empresas` | Listado de empresas con búsqueda HTMX |
| `/empresas/{id}` | Ficha de empresa, empleados y documentos |
| `/empleados` | Listado filtrable de legajos |
| `/empleados/{id}` | Ficha del empleado y recibos |
| `/convenios` | Convenios disponibles |
| `/convenios/{id}` | Detalle normativo y propuestas IA |
| `/liquidaciones` | Historial filtrable |
| `/liquidaciones/{id}` | Resultados, conceptos y recibos |
| `/propuestas-ia` | Bandeja de revisión IA |
| `/propuestas-ia/{id}` | Detalle y acciones de estado |
| `/recibos` | Listado filtrable de recibos |
| `/recibos/{id}` | Detalle con vista previa |
| `/recibos/{id}/vista` | HTML del recibo |
| `/recibos/{id}/pdf` | PDF individual |
| `/recibos/lote.zip` | ZIP de recibos filtrados |
| `/salud` | Health visual |
| `/health/visual` | Alias del health visual |

Las acciones de estado de propuestas solo se ejecutan en el store demo. La
publicación real de reglas debe hacerse en el servicio de IA con permisos y
auditoría; la capa web no duplica esas reglas.

## Autenticación y CSRF

`PAYROLL_WEB_AUTH_ENABLED` vale `true` por defecto. Las rutas privadas usan
`require_web_user` y redirigen a `/login?next=...`; si la petición es HTMX
devuelven `401` con `HX-Redirect`. `/login`, `/salud` y `/static/*` son públicas.

La UI reutiliza `sign_session`, `read_session` y `verify_password` de
`app.auth.security` y la misma cookie que la API. En modo demo las credenciales
se comparan con `PAYROLL_ADMIN_EMAIL` y `PAYROLL_ADMIN_PASSWORD`; en modo SQL se
consulta la tabla `users` (rol `viewer` sólo lectura).

Cada POST valida un token CSRF firmado con `itsdangerous`. El token viaja en la
cookie `payroll_csrf` y en el campo oculto `csrf_token`; ambos deben coincidir y
la firma debe ser válida. También se acepta el header `X-CSRF-Token`.

## Fuente de datos

Las rutas dependen de `get_data_source` y no de una sesión SQL concreta. Por
defecto se crea un `DemoDataStore` en memoria y se guarda en
`request.app.state.payroll_data_source`, de modo que cada aplicación de test
tiene datos aislados.

Para conectar SQLAlchemy, implementar un repositorio con los métodos de
`DemoDataStore` (listados, búsquedas, dashboard) y registrarlo:

```python
from app.database.session import SessionLocal
from app.web.dependencies import get_data_source

application.state.payroll_data_source = SqlAlchemyDataSource(SessionLocal)
# o bien:
application.dependency_overrides[get_data_source] = lambda: SqlAlchemyDataSource(SessionLocal)
```

`get_db` debe usarse dentro de ese repositorio SQL, no en las plantillas ni en
las rutas. Las pruebas de `app/web` no requieren base de datos real.

## Recibos PDF

```python
from app.exporters.pdf.receipts import (
    render_receipt_html,
    render_receipt_pdf,
    render_receipts_zip,
)

html = render_receipt_html(context)
pdf = render_receipt_pdf(context)
zip_bytes = render_receipts_zip([context_1, context_2])
```

El contrato completo del contexto está documentado en
`app/exporters/pdf/receipts.py`. Se aceptan alias en español (`empleador`,
`trabajador`, `conceptos`, `neto`, `periodo`). El renderer:

- valida datos mínimos y tipos de concepto;
- usa autoescape de Jinja2 para datos personales;
- aplica una lista blanca de campos (las claves desconocidas no se imprimen);
- genera PDF con WeasyPrint de forma diferida y un error claro si falta;
- sanea y desduplica los nombres de archivo del ZIP;
- no incluye secretos, claves ni notas internas.

## Pruebas

```bash
.venv/bin/python -m pytest tests/unit/test_web_*.py tests/exporters/test_pdf_*.py -q
```

Los tests no usan red ni base de datos real. El PDF se verifica con `pypdf`
(cantidad de páginas y texto extraíble).
