# Comandos únicos del arranque documentado en README (orden importa, B-22).
# `setup` incluye el paso 0 de B-72: crear .env desde el ejemplo si falta.

.PHONY: setup migrate seed run gates

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
