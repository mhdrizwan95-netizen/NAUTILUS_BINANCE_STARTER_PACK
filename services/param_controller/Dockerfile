FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY services/param_controller/requirements.txt ./requirements.txt
# hadolint ignore=DL3013
RUN pip install --upgrade pip && pip install --require-hashes -r requirements.txt

# Needed for container healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/param_controller/app ./app
COPY services/common /app/common

ENV PC_DB=/shared/param_controller.sqlite

# Run as non-root user
RUN useradd -m appuser \
    && mkdir -p /shared \
    && chown -R appuser:appuser /app /shared

# Add lightweight entrypoint to chown mounted volume then drop privileges
COPY services/param_controller/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8002

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8002"]
