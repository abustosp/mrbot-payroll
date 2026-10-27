# Operaciones

## Salud y logs

La API y el contenedor consultan `GET /health`. Este endpoint prueba una tabla real (`alembic_version`) y responde `{"status": "ok"}` solo si la base migrada responde; si no, responde 503 `{"status": "error"}`. La UI visual equivalente es `GET /salud`.

```sh
docker compose -f deployment/docker-compose.yml ps
docker compose -f deployment/docker-compose.yml logs --follow app
curl --fail http://127.0.0.1:8000/health
```

En ejecución local, los logs salen por stdout. No registrar claves, contraseñas ni datos personales de recibos.

## Backup y restore de SQLite

Detener la aplicación antes de copiar la base para que el archivo y su WAL queden consistentes. Guardar la copia fuera del directorio `data/` y limitar su acceso porque puede contener datos personales.

```sh
docker compose -f deployment/docker-compose.yml stop app
mkdir -p backups
cp data/payroll.db "backups/payroll-$(date +%F-%H%M%S).db"
docker compose -f deployment/docker-compose.yml start app
```

Para restaurar, detener la app, conservar la base actual como respaldo, copiar la copia elegida a `data/payroll.db` y volver a iniciar:

```sh
docker compose -f deployment/docker-compose.yml stop app
cp data/payroll.db "backups/payroll-before-restore-$(date +%F-%H%M%S).db"
cp backups/payroll-AAAA-MM-DD-HHMMSS.db data/payroll.db
docker compose -f deployment/docker-compose.yml start app
```

Si el proceso local está fuera de Docker, detenerlo y aplicar los mismos pasos sobre `data/payroll.db`.

## Checklist trimestral de restore (V2-22)

Probar la restauración cada trimestre en una copia de trabajo y registrar fecha, responsable y resultado antes de darlo por válido:

```sh
mkdir -p /tmp/restore-check && cp "backups/payroll-<fecha>.db" /tmp/restore-check/payroll.db
PAYROLL_DATABASE_URL="sqlite:////tmp/restore-check/payroll.db" .venv/bin/python -m alembic check || true
PAYROLL_DATABASE_URL="sqlite:////tmp/restore-check/payroll.db" .venv/bin/python -c \
  "from sqlalchemy import create_engine, text; e=create_engine('sqlite:////tmp/restore-check/payroll.db'); print(e.connect().execute(text('SELECT count(*) FROM alembic_version')).scalar())"
curl --fail http://127.0.0.1:8000/health
```

Checklist: backup elegido, copia restaurada en directorio temporal, `alembic check` sin pendientes inesperados, lectura de `alembic_version` OK, `/health` en 200 contra la copia (o 503 con causa identificada), registro del ensayo con fecha y responsable.

## Backup en Postgres (V2-22, cuando se active D-2)

El `cp` de SQLite no aplica a Postgres. Con el perfil `postgres`, respaldo lógico programado:

```sh
docker compose -f deployment/docker-compose.yml exec postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "backups/payroll-$(date +%F-%H%M%S).sql"
```

Restaurar en una base vacía de prueba antes de pisar producción y aplicar la misma checklist trimestral de arriba.

## Migraciones

El repositorio incluye `alembic.ini` y la revisión inicial. Respaldar primero y aplicar las migraciones con:

```sh
.venv/bin/python -m alembic upgrade head
```

El contenedor ejecuta ese mismo comando al iniciar, antes de Uvicorn. En
producción, ejecutar la migración una sola vez antes de actualizar réplicas de
la aplicación. No modificar el esquema manualmente. Si se habilita
`PAYROLL_SEED_DEMO=true`, el entrypoint también ejecuta `python -m
scripts.seed_demo`; no usar esa opción con datos reales.

## Actualización de paquetes normativos

Todavía no existe un paquete de datos normativos ni un proceso de actualización implementado. Cuando se agregue, registrar fuente, jurisdicción, vigencia, versión y checksum; revisar cambios con un profesional, correr validaciones y casos de referencia, guardar el paquete anterior y respaldar la base antes de activar la nueva versión. Los datos demo no reemplazan una revisión normativa y no son asesoramiento legal.

## Modelos reservados (B-63, PENDING decisión D-7, 2026-10-26)

`Establishment`, `EmploymentHistory`, `ConceptTaxTreatment` y
`BackgroundJob` (`app/database/models.py:65,115,188,460`) hoy no tienen
ningún consumidor fuera de modelos, la migración y un test de nombres.
NO borrarlos: quedan reservados hasta que D-7 decida entre borrarlos
(con migración) o darles uso. Cada cambio de esquema los arrastra
mientras tanto.

## Alias `document_processing` (B-64, PENDING decisión D-7, 2026-10-26)

`app/ai/document_processing/` re-exporta `app.ai.documents` sin
consumidores propios. NO borrarlo todavía. Plan exacto si D-7 decide
borrar: eliminar el paquete `app/ai/document_processing/`, dejar
`app.ai.documents` como única vía y actualizar `plan.md` §5 si nombra
el paquete.

## Deuda de migración SQLite → Postgres (B-87)

Si se migra (decisión D-2), revisar antes:

- `JSON` genérico (`ConceptTaxTreatment.tax_metadata:195`,
  `FormulaVersion.expression:219`, `AiProposal.raw_json:251` en
  `app/database/models.py`): pasar a `JSONB` donde se filtre por dentro
  del documento.
- `DateTime(timezone=True)` (`app/database/session.py:12-25` y
  modelos): SQLite ignora la zona horaria; Postgres la exige:
  normalizar a UTC al migrar.
- `CHECK` con `CAST`/`SUBSTR` de dialecto: reescribir al dialecto
  Postgres y revalidar.

## Escritorio (B-73, PENDING decisión D-3, 2026-10-26)

`desktop/` no funciona (spec sin templates/estáticos, launcher sin
migrar ni sembrar, puerto fijo, navegador a ciegas) y el README lo
declara no listo. SIN CAMBIOS hasta que D-3 decida. Plan exacto:

- Reparar: empaquetar templates/estáticos en `payroll.spec`
  (`datas=[]` hoy), migrar (`alembic upgrade head`) y sembrar al
  inicio del launcher, evitar el puerto 8000 fijo y esperar al
  backend sano antes de abrir el navegador.
- Borrar: eliminar `desktop/` completo y su workflow
  `build-desktop.yml` hasta que se necesite.

## CORS y CSRF de la API (V2-14)

`PAYROLL_CORS_ORIGINS` vive en `.env.example` (vacío por defecto = sin CORS). Cada origen permitido combina `allow_credentials=true` con la cookie de sesión: es de plena confianza CSRF. Solo abrir el frontend propio por HTTPS y enviar `X-CSRF-Token` en `POST/PUT/PATCH/DELETE` de `/api/` con cookie cuando haya origins configurados. La web Jinja2 ya exige token CSRF con doble submit (`payroll_csrf` + campo oculto).

## Comandos make (B-68P)

Atajos verificados por CI (`.github/workflows/ci.yml`): `make setup` (venv + deps + `.env` + `data/`), `make migrate` (`alembic upgrade head`), `make seed` (demo idempotente), `make run` (uvicorn con reload), `make gates` (pytest + ruff + mypy). Ver `make help` para el listado en terminal.

## Sesiones y cambio de contraseña

`POST /api/v1/auth/change-password` existe y rota `User.session_version`: la cookie anterior queda en 401. Rotar la contraseña inicial `admin/admin` tras el primer arranque y no usar `PAYROLL_SEED_DEMO=true` con datos reales (el seed solo crea el admin si no existe, nunca lo re-escribe). En modo SQL (`PAYROLL_WEB_DATA_SOURCE=sql`) la UI filtra por la organización del usuario autenticado (fail-closed); no exponer la app a Internet sin HTTPS y secreto propio.

## Actualización y recuperación

Antes de actualizar la imagen o el ejecutable, crear y verificar un backup. Desplegar la nueva versión, ejecutar las migraciones disponibles y comprobar `/health` y los logs. Si falla, detener la versión nueva, restaurar el backup previo si hubo cambios de esquema o datos y volver a la versión anterior; conservar logs y la base fallida para investigar.
