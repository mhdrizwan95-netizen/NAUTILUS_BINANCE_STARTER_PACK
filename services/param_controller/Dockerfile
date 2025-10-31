FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY services/param_controller/requirements.txt ./requirements.txt
# hadolint ignore=DL3013
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY services/param_controller/app ./app
COPY services/common /app/common

ENV PC_DB=/shared/param_controller.sqlite

CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8002"]
