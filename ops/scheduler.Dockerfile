FROM python:3.11-slim

# Install supercronic (tiny cron runner)
ARG SUPERCRONIC_VERSION=v0.2.25
ADD https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64 /usr/local/bin/supercronic
RUN chmod +x /usr/local/bin/supercronic \
 && apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip install --no-cache-dir httpx pandas pyarrow numpy ib_insync requests sseclient-py

WORKDIR /app

# Ensure logs directory exists for cron output
RUN mkdir -p /app/logs/cron

CMD ["supercronic", "/app/ops/schedule_backfill.cron"]

