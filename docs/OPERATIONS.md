# Operaciones

## Salud y logs

La API y el contenedor consultan `GET /health`. Este endpoint confirma que FastAPI responde; actualmente no comprueba conexión a la base de datos.

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

Si el proceso local está fuera de Docker, detenerlo y aplicar los mismos pasos sobre `data/payroll.db`. Probar periódicamente la restauración en una copia de trabajo.

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

## Actualización y recuperación

Antes de actualizar la imagen o el ejecutable, crear y verificar un backup. Desplegar la nueva versión, ejecutar las migraciones disponibles y comprobar `/health` y los logs. Si falla, detener la versión nueva, restaurar el backup previo si hubo cambios de esquema o datos y volver a la versión anterior; conservar logs y la base fallida para investigar.
