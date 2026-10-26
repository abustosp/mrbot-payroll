#!/bin/sh
set -eu

alembic upgrade head

if [ "${PAYROLL_SEED_DEMO:-false}" = "true" ]; then
    python -m scripts.seed_demo
fi

exec "$@"

