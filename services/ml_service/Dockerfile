# Multi-stage build to keep runtime lean
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1     PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for scipy/numpy/scikit-learn wheels where needed
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential gcc gfortran     libatlas-base-dev liblapack-dev libblas-dev     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy app code
COPY app ./app

# Runtime env
ENV DATA_DIR=/data     MODEL_DIR=/models     REGISTRY_DIR=/models/registry     CURRENT_SYMLINK=/models/current     LOG_LEVEL=INFO     UVICORN_WORKERS=1     UVICORN_HOST=0.0.0.0     UVICORN_PORT=8000

EXPOSE 8000

# Default runs the inference API (hot-reloads model when /models/current changes)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
