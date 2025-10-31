FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends     build-essential gcc gfortran     libatlas-base-dev liblapack-dev libblas-dev ca-certificates curl     && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY ../common /app/common

ENV DATA_DIR=/data     MODEL_DIR=/models     REGISTRY_DIR=/models/registry     CURRENT_SYMLINK=/models/current     LEDGER_DB=/shared/manifest.sqlite     EXACTLY_ONCE=false     DELETE_AFTER_PROCESS=true     LOG_LEVEL=INFO     UVICORN_HOST=0.0.0.0     UVICORN_PORT=8000

EXPOSE 8000

CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
