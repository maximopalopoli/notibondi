.PHONY: up migrate import holidays dev lint test check fmt pilot

up:
	docker compose up -d --wait

migrate:
	uv run alembic upgrade head

import:
	uv run python -m notibondi.importer data/gtfs.zip

holidays:
	uv run python -m notibondi.holidays holidays.csv

dev:
	uv run uvicorn notibondi.main:app --reload

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest

check: lint test

fmt:
	uv run ruff check --fix .
	uv run ruff format .

pilot:
	uv run --group pilot python pilot/recorder.py
