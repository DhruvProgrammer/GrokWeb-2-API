# syntax=docker/dockerfile:1
# ---- build stage ----
FROM python:3.11-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Install dependencies in a separate layer so source changes don't bust the cache.
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---- runtime stage ----
FROM python:3.11-slim
RUN useradd --create-home --uid 1000 appuser
USER appuser
WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

COPY --chown=appuser:appuser grok_web_to_api ./grok_web_to_api
COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser test-api.sh ./

EXPOSE 4982
# uvicorn entry point keeps the import path stable.
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4982"]