.PHONY: up migrate gtfs import holidays dev lint test check fmt pilot track tiles

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

# The map of the AMBA, cut from Protomaps' daily world build (tiles.py).
# Needs the pmtiles CLI (github.com/protomaps/go-pmtiles) in the PATH.
# BUILD is a date with a build: https://maps.protomaps.com/builds
# make tiles BUILD=20261118 NAME=amba-2026-11
AMBA_BBOX = -60.98,-35.19,-57.72,-34.04
tiles:
	pmtiles extract https://build.protomaps.com/$(BUILD).pmtiles data/tiles/$(NAME).pmtiles --bbox=$(AMBA_BBOX)
