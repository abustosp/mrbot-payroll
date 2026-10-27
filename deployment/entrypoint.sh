#!/bin/sh
set -eu

# B-16: fuera de development, secreto vacio o igual al ejemplo = sesiones
# forjables; fallar antes de migrar (la app tambien lo rechaza en config).
if [ "${PAYROLL_ENVIRONMENT:-development}" != "development" ]; then
    case "${PAYROLL_SECRET_KEY:-}" in
        ""|"change-me-in-production")
            echo "ERROR: PAYROLL_SECRET_KEY debe definirse con un valor propio cuando PAYROLL_ENVIRONMENT no es 'development'." >&2
            exit 1
            ;;
    esac
fi

# B-71: con el perfil postgres activo, password vacio = base inaccesible;
# fallar con el remedio en vez de arrancar a ciegas.
case ",${COMPOSE_PROFILES:-}," in
    *,postgres,*)
        if [ -z "${POSTGRES_PASSWORD:-}" ]; then
            echo "ERROR: POSTGRES_PASSWORD debe tener un valor no vacío con el perfil postgres activo." >&2
            exit 1
        fi
        ;;
esac

# B-22/V2-08: tolerar solo una base ya creada por create_all sin sellar
# (el upgrade falla con "table ... already exists"): sellar y reintentar una
# vez unicamente en ese caso; cualquier otro fallo aborta con el remedio para
# no marcar una migracion rota como aplicada.
if upgrade_out=$(alembic upgrade head 2>&1); then
    printf '%s\n' "$upgrade_out"
else
    printf '%s\n' "$upgrade_out" >&2
    case "$upgrade_out" in
        *[Aa]lready*[Ee]xists*)
            alembic stamp head
            alembic upgrade head
            ;;
        *)
            echo "ERROR: 'alembic upgrade head' fallo. Revisar la migracion y reintentar; no se sello nada." >&2
            exit 1
            ;;
    esac
fi

if [ "${PAYROLL_SEED_DEMO:-false}" = "true" ]; then
    python -m scripts.seed_demo
fi

exec "$@"

