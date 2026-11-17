# Stage 1: install the dependencies and the app into .venv with uv.
# Dependencies go first, so code changes don't reinstall them.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable


# Stage 2: a clean Python image with only .venv, run by a non-root user.
FROM python:3.14-slim
RUN useradd --system --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000

# A single worker: each one would start its own background tasks.
CMD ["uvicorn", "notibondi.main:app", "--host", "0.0.0.0", "--port", "8000"]
