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

## Actualización y recuperación

Antes de actualizar la imagen o el ejecutable, crear y verificar un backup. Desplegar la nueva versión, ejecutar las migraciones disponibles y comprobar `/health` y los logs. Si falla, detener la versión nueva, restaurar el backup previo si hubo cambios de esquema o datos y volver a la versión anterior; conservar logs y la base fallida para investigar.
