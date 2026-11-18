.PHONY: up migrate gtfs import holidays dev lint test check fmt pilot track

up:
	docker compose up -d --wait db

migrate:
	uv run alembic upgrade head

gtfs:
	uv run python -m notibondi.download_gtfs data/gtfs.zip

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
	uv run python pilot/recorder.py

track:
	uv run python pilot/tracker.py
