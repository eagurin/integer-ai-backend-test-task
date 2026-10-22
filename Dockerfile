FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /service

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --group dev --no-install-project

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY compose.yaml ./
COPY tests ./tests
RUN uv sync --locked --group dev

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
