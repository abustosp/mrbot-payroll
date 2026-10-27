# Comandos únicos del arranque documentado (orden importa, B-22).
# `setup` incluye el paso 0 de B-72: crear .env desde el ejemplo si falta.
# Ver tambien docs/OPERATIONS.md ("Comandos make", B-68P).

.PHONY: setup migrate seed run gates help

help: ## Lista los comandos disponibles
	@echo "Comandos disponibles:"
	@echo "  make setup   - crea .venv, instala dev, copia .env.example y crea data/"
	@echo "  make migrate - aplica migraciones (alembic upgrade head)"
	@echo "  make seed    - carga datos demo (idempotente, no re-escribe el admin)"
	@echo "  make run     - sirve la app con uvicorn --reload"
	@echo "  make gates   - pytest + ruff + mypy (mismo gate que CI)"

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -e ".[dev]"
	[ -f .env ] || cp .env.example .env
	mkdir -p data

migrate:
	.venv/bin/python -m alembic upgrade head

seed:
	.venv/bin/python -m scripts.seed_demo

run:
	.venv/bin/python -m uvicorn app.main:app --reload

gates:
	.venv/bin/python -m pytest --cov=app --cov-fail-under=80
	.venv/bin/python -m ruff check .
	.venv/bin/python -m mypy app scripts alembic
