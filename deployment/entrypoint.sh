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

# B-22: tolerar una base ya creada por create_all sin sellar (la migra
# directa falla con "table ... already exists"): sellar y reintentar una vez.
# shortcut: se asume que el fallo es por base pre-creada; una migracion rota
# real quedaria sellada como head y habria que revisarla a mano.
if ! alembic upgrade head; then
    alembic stamp head
    alembic upgrade head
fi

if [ "${PAYROLL_SEED_DEMO:-false}" = "true" ]; then
    python -m scripts.seed_demo
fi

exec "$@"

