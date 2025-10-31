FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
# hadolint ignore=DL3013
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY app ./app
ENV DATASET=/historical/sample.csv     START=0     END=0     STEP_MINUTES=5     RETRAIN_EVERY_MIN=360     EXACTLY_ONCE=true     COST_BPS=1.0     SLIPPAGE_BPS_PER_VOL=2.0
CMD ["python","-m","app.main"]
