FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/backtest_suite/requirements.txt ./requirements.txt
# hadolint ignore=DL3013
RUN pip install --upgrade pip && pip install --require-hashes -r requirements.txt

COPY services/backtest_suite/app ./app
COPY services/common /app/common

ENV LEDGER_DB=/research/manifest.sqlite     RESEARCH_DIR=/research     DATA_INCOMING=/research/incoming     ML_SERVICE=http://ml_service:8000     PARAM_CONTROLLER=http://param_controller:8002     LOG_LEVEL=INFO

# Run as non-root user
RUN useradd -m appuser \
    && mkdir -p /research /research/incoming /data /shared \
    && chown -R appuser:appuser /app /research /data /shared
USER appuser

ENTRYPOINT ["python","-m","app.cli"]
