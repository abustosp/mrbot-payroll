# Mrbot Payroll

Mrbot Payroll es un prototipo MVP de liquidación de sueldos para Argentina. Combina
un motor de cálculo determinista con un flujo de inteligencia artificial
supervisada: la IA interpreta documentos y propone reglas, pero no calcula
liquidaciones oficiales ni publica reglas por sí sola.

El repositorio ya permite ejecutar un flujo de demostración completo: iniciar
sesión, crear una liquidación, calcularla con fórmulas versionadas, aprobarla y
generar un recibo PDF o un TXT de Libro de Sueldos Digital. Ese flujo usa datos
demo y no constituye una implementación lista para producción.

> **Advertencia:** los parámetros, escalas y ejemplos incluidos son ilustrativos.
> No son asesoramiento legal y no deben usarse para liquidaciones reales ni para
> presentaciones ante ARCA. Ver `docs/NORMATIVE_DATA.md`.

## Estado actual

| Área | Estado | Alcance real |
|---|---|---|
| FastAPI y `/health` | Implementado | Responde JSON; 503 si la base no responde (prueba `alembic_version`) |
| Autenticación API y UI | Implementado | Cookie firmada, PBKDF2, roles y CSRF en la UI web |
| Persistencia | Implementado | SQLAlchemy 2.x, Alembic, SQLite local y PostgreSQL por URL |
| API de negocio | Implementado | Empresas, empleados, convenios, conceptos, fórmulas, liquidaciones, importación y reportes |
| Motor de cálculo | Implementado | DSL declarativo, dependencias, `Decimal`, novedades y bases |
| Cálculo persistente | Implementado | Servicio que calcula una corrida y guarda resultados y trazas |
| Proveedor Argentina | Implementado como demo | CCT 130/75 acotado y parámetros ilustrativos |
| IA supervisada | Implementado | Extracción, análisis, validación, persistencia y publicación manual como fórmula borrador |
| API de IA | Implementado con `MockProvider` | Para un proveedor real hay que inyectar la dependencia en código |
| UI web | Implementado | Demo por defecto o lectura SQL opcional; login y CSRF |
| Recibos PDF | Implementado | HTML, PDF individual y ZIP; sin validación legal |
| TXT Libro de Sueldos Digital | MVP técnico | Ancho fijo y Latin-1; sin aceptación de ARCA |
| Importadores CSV/XLSX | Implementado | API con dry-run; alta idempotente de empleados y novedades |
| Paquetes normativos CCT | Implementado | 11 CCT, 254 documentos y 786 escalas verificadas (778 desde 2020 y 8 históricas) |
| Liquidaciones especiales | Implementado como módulo y API | SAC, vacaciones y final; todavía no se eligen desde el tipo de corrida |
| Reporte F.931 | Implementado como planilla interna | XLSX de control, sin formato oficial ni presentación ARCA |
| Docker y ejecutable | Configuración inicial | No hay builds verificados en este repositorio |

La autenticación, la API, el motor de fórmulas, el cálculo, el flujo de IA, la
importación, la evidencia CCT y los reportes internos existen. Lo que sigue
pendiente es filtrar fórmulas y parámetros por convenio/categoría, integrar
SAC/vacaciones/final al tipo de corrida, validar los formatos contra ARCA y
completar el endurecimiento para producción.

## Requisitos

- Python 3.11 o superior.
- pip y un entorno virtual para desarrollo local.
- Docker con Compose v2 para la modalidad de contenedor.
- PyInstaller solo si se quiere intentar compilar el ejecutable.
- WeasyPrint requiere bibliotecas nativas y fuentes. El contenedor las incluye;
  el ejecutable no las empaqueta.

## Instalación local

Desde la raíz del repositorio:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
[ -f .env ] || cp .env.example .env
mkdir -p data
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m scripts.seed_demo
.venv/bin/python -m uvicorn app.main:app --reload
```

La aplicación queda en <http://127.0.0.1:8000>. El health técnico es
<http://127.0.0.1:8000/health>, la documentación OpenAPI está en `/docs` y la
interfaz web en `/`.

En Windows PowerShell, crear el entorno con `py -3.12 -m venv .venv`, activarlo
con `.venv\Scripts\Activate.ps1` y usar `python` en los comandos siguientes.

### Seed de demostración

`python -m scripts.seed_demo` crea o actualiza, de forma idempotente:

- la organización demo y el usuario `admin@example.com` con contraseña `admin`;
- una empresa demo;
- el convenio CCT 130/75, dos categorías y sus escalas;
- dos empleados con contrato;
- tres conceptos y fórmulas aprobadas;
- parámetros normativos de ejemplo.

Se puede ejecutar más de una vez sin duplicar registros. El comando crea las
tablas si no existen, pero si se usa Alembic conviene ejecutar
`.venv/bin/python -m alembic upgrade head` antes del seed.

Las credenciales del seed son deliberadamente débiles. Cambiar la contraseña y
`PAYROLL_SECRET_KEY` antes de cualquier uso compartido. El `.env.example` deja
`PAYROLL_SECRET_KEY` vacío, así que hay que completar un valor propio. El seed
también restablece la contraseña de `admin@example.com` a `admin` si encuentra
otra. Para rotar la contraseña existe `POST /api/v1/auth/change-password`
(exige la actual, rota `session_version` e invalida las sesiones anteriores);
no hay un bootstrap de usuarios para producción.

La interfaz arranca en modo demo por defecto. Para que muestre los datos
cargados en SQLite, agregar `PAYROLL_WEB_DATA_SOURCE=sql` a `.env` y reiniciar la
aplicación. Ese modo es de solo lectura.

La UI exige login en ambos modos (`PAYROLL_WEB_AUTH_ENABLED=true` por defecto).
En modo demo valida `PAYROLL_ADMIN_EMAIL` y `PAYROLL_ADMIN_PASSWORD`; en modo SQL
consulta la tabla `users` con el mismo hash PBKDF2 y la misma cookie firmada que
la API. Los formularios POST de la UI usan un token CSRF firmado con doble
submit. Para operar el modo SQL hay que sembrar primero un usuario con
`.venv/bin/python -m scripts.seed_demo`.

## Tests y estilo

```sh
.venv/bin/python -m pytest --cov=app --cov-fail-under=80
.venv/bin/ruff check .
```

El gate de cobertura exige al menos 80 % (`make gates` ejecuta pytest con
cobertura, ruff y mypy). La suite no usa red ni una base externa. Cubre el
motor de fórmulas, cálculo, bases imponibles, proveedor argentino, API,
autenticación, web, importadores, exportadores y un flujo de integración con
seed, cálculo, recálculo y salidas.

Para ejecutar solo una parte:

```sh
.venv/bin/python -m pytest tests/payroll -q
.venv/bin/python -m pytest tests/integration -q
```

## API

La API está bajo `/api/v1`. Usa JSON, devuelve errores con la forma
`{"detail": ...}` y protege las rutas con una cookie de sesión. Los listados
aceptan `limit` y `offset`.

### Autenticación

```sh
curl -c cookies.txt -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"admin"}'

curl -b cookies.txt http://127.0.0.1:8000/api/v1/companies
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/v1/auth/logout
```

Roles:

- `viewer`: lectura.
- `editor`: lectura, altas o modificaciones de negocio, cálculo y validación o
  aprobación de propuestas de IA.
- `admin`: además, eliminaciones y aprobaciones de fórmulas y liquidaciones.

### UI web

La interfaz usa las mismas credenciales y la misma cookie que la API, pero con
formularios HTML en `/login` y `/logout`. Las rutas de negocio redirigen a
`/login?next=...` cuando no hay sesión; las peticiones HTMX reciben `401` con
`HX-Redirect`. `/login`, `/salud` y `/static/*` son públicos.

Todos los POST de la UI validan un token CSRF firmado y ligado a la sesión,
enviado como cookie `payroll_csrf` y campo oculto `csrf_token`. Los roles
`admin` y `editor` pueden cambiar el estado de una propuesta; `viewer` sólo
puede leer.

### Endpoints principales

| Método y ruta | Uso |
|---|---|
| `POST /api/v1/auth/login` | Iniciar sesión y recibir la cookie |
| `POST /api/v1/auth/logout` | Cerrar sesión |
| `GET /api/v1/auth/me` | Usuario autenticado |
| `GET, POST /api/v1/companies` | Listar y crear empresas |
| `GET, PUT, DELETE /api/v1/companies/{id}` | Consultar, editar o eliminar |
| `GET, POST /api/v1/employees` | Listar y crear empleados |
| `GET, PUT, DELETE /api/v1/employees/{id}` | Consultar, editar o eliminar |
| `GET, POST /api/v1/agreements` | Listar y crear convenios |
| `GET, PUT, DELETE /api/v1/agreements/{id}` | Consultar, editar o eliminar |
| `GET, POST /api/v1/concepts` | Listar y crear conceptos |
| `GET, PUT, DELETE /api/v1/concepts/{id}` | Consultar, editar o eliminar |
| `GET, POST /api/v1/formulas` | Listar y crear fórmulas en borrador |
| `POST /api/v1/formulas/{id}/versions` | Crear una nueva versión en borrador |
| `POST /api/v1/formulas/{id}/validate` | Validar el DSL |
| `POST /api/v1/formulas/{id}/approve` | Aprobar una fórmula validada |
| `GET, POST /api/v1/payroll-runs` | Listar y crear liquidaciones |
| `GET, PUT, DELETE /api/v1/payroll-runs/{id}` | Consultar, editar o eliminar |
| `POST /api/v1/payroll-runs/{id}/calculate` | Calcular y persistir resultados |
| `POST /api/v1/payroll-runs/{id}/approve` | Aprobar una liquidación calculada |
| `POST /api/v1/exports/lsd/liquidations` | Generar TXT de liquidaciones |
| `POST /api/v1/exports/lsd/concepts` | Generar TXT de conceptos |
| `POST /api/v1/exports/receipts/{result_id}` | Generar el PDF de un resultado |
| `POST /api/v1/ai/analyze-agreement` | Analizar un texto y devolver propuestas |
| `POST /api/v1/ai/proposals/validate` | Validar una propuesta |
| `POST /api/v1/ai/proposals/approve` | Registrar una aprobación humana |
| `POST /api/v1/ai/proposals` | Persistir un análisis como propuesta borrador |
| `POST /api/v1/ai/proposals/{id}/approve` | Aprobar una propuesta persistida |
| `POST /api/v1/ai/proposals/{id}/publish` | Crear una fórmula borrador desde una propuesta aprobada |
| `POST /api/v1/imports/employees` | Importar empleados desde CSV/XLSX, con dry-run |
| `POST /api/v1/imports/novelties` | Validar o persistir novedades CSV/XLSX |
| `GET /api/v1/normative-packages/ccts` | Listar convenios cargados desde paquetes |
| `POST /api/v1/normative-packages/import` | Validar o importar `catalog.json` |
| `GET /api/v1/reports/f931/{run_id}.xlsx` | Generar la planilla interna F.931 |
| `POST /api/v1/settlements/sac` | Simular SAC |
| `POST /api/v1/settlements/vacations` | Simular vacaciones |
| `POST /api/v1/settlements/final` | Simular liquidación final |

Los endpoints de exportación LSD reciben los datos en el cuerpo JSON y no
consultan una liquidación persistida. El de recibos sí parte de un
`PayrollResult` guardado y comprueba la organización del usuario.

`POST /api/v1/payroll-runs/{id}/calculate` es idempotente: reemplaza los
resultados anteriores de la corrida. Toma solo fórmulas `APPROVED` vigentes,
escala, contrato y novedades del período, y deja la corrida en `CALCULATED` o
`ERROR`. La aprobación posterior exige estado calculado o en revisión y rol
`admin`.

La API de IA usa `MockProvider` por defecto. Las propuestas se pueden persistir,
aprobar y publicar manualmente como una `FormulaVersion` en estado `DRAFT`;
nunca se aprueban ni se publican solas. Para un proveedor real hay que
sobrescribir la dependencia `get_ai_provider` en código. Ver
`docs/ARCHITECTURE.md`.

## Interfaz web

La UI está montada en `/` con Jinja2, HTMX y CSS local. Funciona sin CDN.

Tiene dos fuentes de datos:

- `PAYROLL_WEB_DATA_SOURCE=demo` es el valor por defecto y usa un
  `DemoDataStore` en memoria. Los cambios desaparecen al reiniciar y no se
  reflejan en SQLAlchemy.
- `PAYROLL_WEB_DATA_SOURCE=sql` usa `SqlAlchemyDataSource`, una proyección de
  solo lectura sobre las tablas reales. Requiere migración y datos cargados. La
  bandeja de propuestas de la UI lista las propuestas persistidas en
  `ai_proposals`, que requieren revisión humana antes de aprobarse.

La UI exige login en ambos modos y protege los POST con CSRF. En modo SQL la
proyección se filtra por la organización del usuario autenticado (sin
organización no se devuelve ninguna fila). No exponer la UI a Internet.

| Ruta | Pantalla |
|---|---|
| `/` | Dashboard |
| `/empresas` y `/empresas/{id}` | Empresas |
| `/empleados` y `/empleados/{id}` | Legajos |
| `/convenios` y `/convenios/{id}` | Convenios y propuestas |
| `/liquidaciones` y `/liquidaciones/{id}` | Historial y detalle |
| `/propuestas-ia` y `/propuestas-ia/{id}` | Bandeja de revisión (demo y SQL) |
| `/recibos` y `/recibos/{id}` | Recibos |
| `/recibos/{id}/vista` | HTML del recibo |
| `/recibos/{id}/pdf` | PDF individual |
| `/recibos/lote.zip` | ZIP de recibos filtrados |
| `/salud` y `/health/visual` | Estado visual de componentes |

La UI exige login y CSRF. Las acciones de estado de una propuesta funcionan en
ambos modos (demo y SQL); la publicación real de reglas sigue haciéndose en el
servicio de IA con permisos y auditoría. No debe exponerse a Internet ni usarse
con datos personales reales.

`GET /health` sigue siendo el health técnico en JSON (prueba `alembic_version`;
503 si la base no responde). El health visual `/salud` comprueba la conexión
SQL en modo SQL (tabla `users` legible); no comprueba el estado real de una
liquidación.

## Docker

La configuración está en `deployment/`. La imagen aplica `alembic upgrade head`
al iniciar. El seed demo es opcional y se habilita con
`PAYROLL_SEED_DEMO=true`; nunca se ejecuta por defecto.

```sh
[ -f .env ] || cp .env.example .env
mkdir -p data
docker compose --env-file .env -f deployment/docker-compose.yml config
docker compose --env-file .env -f deployment/docker-compose.yml up --build -d
docker compose --env-file .env -f deployment/docker-compose.yml ps
docker compose --env-file .env -f deployment/docker-compose.yml logs -f app
```

Para cargar la demo dentro del contenedor, definir `PAYROLL_SEED_DEMO=true` en
`.env` antes de iniciar. Eso crea `admin@example.com/admin` y los datos
ilustrativos; cambiar la contraseña y el secreto antes de compartir la
instancia.

Para detener:

```sh
docker compose --env-file .env -f deployment/docker-compose.yml down
```

La imagen ejecuta Uvicorn, incluye `psycopg`, monta `data/` como volumen y
arranca el entrypoint que migra la base. El perfil `postgres` levanta
PostgreSQL 16; para usarlo hay que definir `PAYROLL_DATABASE_URL` con el
usuario, la contraseña y la base del servicio. El compose pasa
`PAYROLL_WEB_DATA_SOURCE` al contenedor; usar `sql` para leer la base real.
Tampoco se verificó un build de Docker en este entorno de trabajo. La imagen no
está probada.

La imagen corre como usuario `app` (uid 10001) y SQLite vive en el bind mount
`data/`: ese directorio debe pertenecer al UID/GID con el que corre el
contenedor. Compose ya fija `user: "${PAYROLL_UID:-1000}:${PAYROLL_GID:-1000}"`,
así que `PAYROLL_UID`/`PAYROLL_GID` en `.env` deben coincidir con el dueño de
`data/` en el host (`ls -nd data`). Si no coinciden, el arranque falla con
`sqlite3.OperationalError: unable to open database file`; en ese caso ajustar
`.env` o cambiar el dueño con `sudo chown -R "$(id -u):$(id -g)" data`.

## Ejecutable de escritorio

Los scripts de compilación existen, pero no se verificó un build de PyInstaller:

```sh
.venv/bin/python -m pip install pyinstaller
PYTHON=.venv/bin/python desktop/build-linux.sh
dist/mrbot-payroll/mrbot-payroll
```

En Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
$env:PYTHON = ".venv\Scripts\python.exe"
.\desktop\build-windows.ps1
.\dist\mrbot-payroll\mrbot-payroll.exe
```

El launcher escucha solo en `127.0.0.1` y guarda SQLite en el directorio de
datos del usuario. El `.spec` no incluye plantillas, archivos estáticos ni
bibliotecas nativas de WeasyPrint, y el ejecutable no ejecuta migraciones ni
seed. Por eso no está listo para uso general sin completar el empaquetado y el
arranque de la base.

## Variables de entorno

Las variables de configuración usan el prefijo `PAYROLL_` y se leen desde `.env`.

| Variable | Valor por defecto | Uso |
|---|---|---|
| `PAYROLL_APP_NAME` | `Payroll Argentina` | Nombre de la aplicación |
| `PAYROLL_ENVIRONMENT` | `development` | Entorno informado |
| `PAYROLL_DEBUG` | `false` | Modo debug |
| `PAYROLL_SECRET_KEY` | `change-me-in-production` | Firma de la cookie; cambiar siempre |
| `PAYROLL_DATABASE_URL` | `sqlite:///./data/payroll.db` | URL SQLAlchemy |
| `PAYROLL_SESSION_COOKIE` | `payroll_session` | Nombre de la cookie |
| `PAYROLL_ADMIN_EMAIL` | `admin@example.com` | Admin del login web en modo demo; no lo usa el seed actual |
| `PAYROLL_ADMIN_PASSWORD` | `admin` | Contraseña del login web en modo demo; no la usa el seed actual |
| `PAYROLL_CORS_ORIGINS` | lista vacía | Orígenes permitidos, en formato JSON |
| `PAYROLL_COOKIE_SECURE` | `false` | Cookie solo por HTTPS |
| `PAYROLL_SESSION_MAX_AGE` | `28800` | Duración de la sesión en segundos |
| `PAYROLL_WEB_DATA_SOURCE` | `demo` | Fuente de la UI: `demo` o `sql` |
| `PAYROLL_WEB_AUTH_ENABLED` | `true` | Exige login y CSRF en la UI web |
| `PAYROLL_SEED_DEMO` | `false` | Ejecuta el seed demo al iniciar el contenedor |
| `PAYROLL_NORMATIVE_CCT_DIR` | `normative/cct` | Directorio del catálogo CCT y sus PDFs |

El proveedor compatible con OpenAI lee, si se construye explícitamente:

- `PAYROLL_AI_API_KEY`;
- `PAYROLL_AI_BASE_URL`;
- `PAYROLL_AI_MODEL`.

También acepta `OPENAI_API_KEY`, `OPENAI_BASE_URL` y `OPENAI_MODEL` como
alternativa. La API montada no usa estas variables mientras siga con
`MockProvider`.

Docker Compose usa además `PAYROLL_UID`, `PAYROLL_GID`, `POSTGRES_DB`,
`POSTGRES_USER` y `POSTGRES_PASSWORD`. Para PostgreSQL en una instalación local,
instalar el extra con `.venv/bin/python -m pip install -e ".[postgres]"`.

## Estructura

```text
app/
├── api/                 API REST /api/v1
├── auth/                Sesiones, contraseñas y roles
├── ai/                  Extracción, análisis, validación y propuestas
├── core/
│   ├── normative/       Parámetros con vigencia
│   └── payroll_engine/  DSL, dependencias, cálculo y bases
├── database/            Modelos SQLAlchemy y sesión
├── exporters/
│   ├── pdf/             Recibos HTML/PDF
│   └── txt/             Libro de Sueldos Digital
├── importers/           Lectura y validación CSV/XLSX
├── jurisdictions/
│   └── argentina/       Proveedor y datos demo de Argentina
├── services/            Cálculo persistente de una corrida
├── web/                 UI Jinja2, HTMX y fuentes demo/SQL
├── config.py
└── main.py
alembic/                 Migración inicial
scripts/seed_demo.py     Seed idempotente de demostración
tests/                   Unitarios, integración y casos por dominio
desktop/                 Launcher y scripts de PyInstaller
deployment/              Dockerfile y Compose
docs/                    Arquitectura, datos normativos y operaciones
```

## Datos normativos y límites

Los parámetros del seed y del proveedor Argentina siguen siendo demo. El
catálogo `normative/cct/` reúne 11 CCT, 254 documentos oficiales y **786 escalas
verificadas**: 778 con vigencia desde 2020 y 8 históricas de 2007, incluidas
escalas programadas para noviembre y diciembre de 2026. Las fuentes, hashes y notas están en
`normative/cct/evidence/`. Los PDFs crudos de evidencia quedan en el working
tree pero no se versionan por tamaño; las URLs y hashes sí.

El exportador LSD respeta anchos y codificación, pero no fue validado contra la
especificación oficial vigente ni contra el entorno de ARCA. Los registros 05,
06 y el layout de conceptos usan campos de reserva o estructuras de muestra. No
se debe afirmar que el archivo es aceptado por ARCA.

Para reemplazar la demo y validar las salidas, ver `docs/NORMATIVE_DATA.md`.

## Limitaciones principales

- Es un MVP en desarrollo, no un sistema de producción.
- No usar con datos personales reales ni para liquidaciones oficiales.
- La UI web ya exige login y protección CSRF. En modo demo no persiste; en modo
  SQL filtra por la organización del usuario autenticado.
- La API de IA usa un mock por defecto; la persistencia y publicación existen,
  pero el proveedor real se inyecta en código.
- La publicación de una propuesta crea una fórmula en `DRAFT`; no la aprueba
  ni la activa.
- SAC, vacaciones y liquidación final tienen API de simulación, pero todavía no
  se eligen automáticamente desde el tipo de corrida ni desde la UI.
- El reporte F.931 es una planilla interna de control, no el formato oficial.
- El cálculo cubre una corrida mensual básica. No incluye retroactivos
  complejos ni asientos contables.
- No hay trabajos en segundo plano en uso ni auditoría automática de CRUD.
- Hay rate limiting de login en memoria, cambio de contraseña e invalidación de
  sesiones por versión. Faltan MFA, recuperación y rate limiting compartido.
- Los valores por defecto de secreto y admin son inseguros.
- El TXT LSD no está aceptado por ARCA y el recibo no acredita firma o entrega.
- Docker y PyInstaller tienen configuración inicial, pero no builds verificados.
- El ejecutable no ejecuta migraciones ni seed; la imagen Docker sí.

## Documentación

- `docs/ARCHITECTURE.md`: componentes, flujo, seguridad y auditoría.
- `docs/AUDIT_2026-10-26.md`: hallazgos de la auditoría y correcciones aplicadas.
- `docs/NORMATIVE_DATA.md`: datos demo, versionado y validación pendiente.
- `docs/OPERATIONS.md`: salud, backups y operación.
- `docs/IMPLEMENTATION_CONTRACTS.md`: contratos entre módulos.
- `plan.md`: plan funcional de referencia.
