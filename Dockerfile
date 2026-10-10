FROM python:3.12-slim

WORKDIR /app

# Install uv (versión fija: una nueva no debe romper el build sin aviso)
COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* ./

# Install production dependencies only
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY app/ ./app/
COPY main.py ./

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# El hosting (Render) asigna el puerto en PORT; en local queda el 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
