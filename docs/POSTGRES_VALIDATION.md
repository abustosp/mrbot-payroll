# Validación en PostgreSQL

## Reproducir

Se requiere PostgreSQL accesible, una base de pruebas y un usuario con permiso
para crear y eliminar esquemas. Instalar las dependencias y configurar la URL
de esa base, sin compartir credenciales:

```bash
uv sync --frozen --extra dev --extra postgres
export PAYROLL_TEST_POSTGRES_URL='postgresql+psycopg://USUARIO:CLAVE@HOST:5432/BASE_DE_PRUEBA'
uv run --no-sync pytest tests/postgres
uv run --no-sync python scripts/benchmark_postgres_payroll.py --employees 1000 --iterations 3
```

El benchmark también acepta `--url`; por defecto usa 1.000 empleados y tres
iteraciones. Los valores de ambos parámetros deben ser positivos. El JSON se
escribe en stdout y el registro de migraciones en stderr.

Cada prueba y cada ejecución del benchmark crean un esquema con UUID propio,
configuran `search_path` a ese esquema y lo eliminan al finalizar, con sus
objetos. No se elimina la base ni se modifican los demás esquemas. Si el proceso
se termina abruptamente antes de ejecutar su limpieza, el esquema temporal puede
requerir eliminación manual. Las pruebas se omiten si no se configura la URL.

## Evidencia del 28 de octubre de 2026

En el árbol de trabajo actual, contra PostgreSQL 16.15 local en contenedor,
Python 3.12.3 y Linux (16 procesadores lógicos visibles), pasaron cinco pruebas
PostgreSQL: migración con resultados previos y protección contra downgrade con
pérdida, ciclo mensual con importación y reparación, rechazo de cálculo de una
sesión desactualizada, bloqueo real entre importación y aprobación y snapshots
independientes de dos liquidaciones concurrentes. El bloqueo de aprobación se
observó mediante `pg_stat_activity` antes de liberar la importación.

El benchmark ejecutó tres veces la misma liquidación mensual de 1.000 empleados,
con datos demo, tres conceptos distintos y 3.000 ítems persistidos. Cada tiempo
incluye el cálculo y su commit; excluye la migración y la carga inicial. La
respuesta se solicitó con `include_items=False`.

| Iteración | Segundos |
| --- | ---: |
| 1 | 1,871788 |
| 2 | 2,137026 |
| 3 | 2,445944 |
| Mediana | 2,137026 |

Los tres hashes de resultados coincidieron:
`0ff259616cfbc921f7e77727479863392228eac7cb965b9b737dab8504bb93f6`.
La medición corresponde a un único proceso y una base local con datos de prueba;
no mide usuarios concurrentes, latencia de red ni capacidad de producción.
