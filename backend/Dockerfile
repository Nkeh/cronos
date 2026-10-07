# Shared image for api, runner, notifier and migrate — they differ only by
# the `command:` compose sets, not by what's installed.
FROM python:3.12-slim-bookworm@sha256:7753c33391fc9f01d1984375bf375eb6686d52ba10db6043a86634a5ccf90dcf

COPY --from=ghcr.io/astral-sh/uv@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 /uv /uvx /usr/local/bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first so the venv layer (at /opt/venv, outside /app) is cached
# independently of source changes. The dev bind mount later overlays only
# /app, so it can never shadow /opt/venv with an empty host directory.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY healthcheck_http.py healthcheck_alive.py ./

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
