.PHONY: up migrate dev lint test check fmt

up:
	docker compose up -d --wait

migrate:
	uv run alembic upgrade head

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
