FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        gfortran \
        libopenblas-dev \
        liblapack-dev \
        libblas-dev \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/ml_service/requirements.txt ./requirements.txt
# hadolint ignore=DL3013
RUN pip install --upgrade pip && pip install --require-hashes -r requirements.txt

COPY services/ml_service/app ./app
COPY services/common /app/common

ENV DATA_DIR=/ml/data     MODEL_DIR=/models     REGISTRY_DIR=/models/registry     CURRENT_SYMLINK=/models/current     LEDGER_DB=/ml/manifest.sqlite     EXACTLY_ONCE=true     DELETE_AFTER_PROCESS=true     LOG_LEVEL=INFO     UVICORN_HOST=0.0.0.0     UVICORN_PORT=8000

# Run as non-root user
RUN useradd -m appuser \
    && mkdir -p /ml/data /models \
    && chown -R appuser:appuser /app /ml /models
USER appuser

EXPOSE 8000

CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
