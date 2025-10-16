SHELL := /bin/bash
ROOT  := $(shell pwd)

# Docker compose files
MAIN_COMPOSE := docker-compose.yml
OBS_COMPOSE  := ops/observability/docker-compose.observability.yml

# Default target
.DEFAULT_GOAL := start

# --- Legacy shortcuts --------------------------------------------------------

up:
	docker compose up -d --build

down:
	docker compose down

ps:
	docker compose ps

reup: down up logs

# --- Unified controls --------------------------------------------------------

deps:
	@# Optionally install local Python deps so `make` works outside Docker
	@if [ "$$SKIP_DEPS" = "1" ]; then \
	  echo "⏭️  SKIP_DEPS=1 set; skipping local pip install"; \
	else \
	  if command -v python3 >/dev/null 2>&1; then \
	    echo "📦 Installing Python deps locally (python3 -m pip)"; \
	    python3 -m pip install -r requirements.txt || true; \
	  elif command -v python >/dev/null 2>&1; then \
	    echo "📦 Installing Python deps locally (python -m pip)"; \
	    python -m pip install -r requirements.txt || true; \
	  else \
	    echo "⚠️  No python found; relying on Docker build to install deps"; \
	  fi; \
	fi

build:
	@echo "🔧 Building all core services..."
	docker compose -f $(MAIN_COMPOSE) build

start: deps build
	@echo "🚀 Starting main trading stack..."
	docker compose -f $(MAIN_COMPOSE) up -d situations universe screener ops engine_binance engine_ibkr engine_bybit || true
	@if [ -f "$(OBS_COMPOSE)" ]; then \
		echo "📊 Starting observability stack..."; \
		docker compose -f $(OBS_COMPOSE) up -d; \
	else \
		echo "⚠️  No observability compose file found; skipping."; \
	fi
	@echo "🧠 Starting backfill trainer (continuous historical learner)..."
	docker compose -f $(MAIN_COMPOSE) up -d backfill || true
	@echo
	@echo "✅ System running. Check:"
	@echo "   Situations  → http://localhost:8011/health"
	@echo "   Universe    → http://localhost:8009/health"
	@echo "   Screener    → http://localhost:8010/health"
	@echo "   Ops API     → http://localhost:8002/status"
	@echo

backfill:
	@echo "🧠 (Re)building backfill scheduler service..."
	docker compose -f $(MAIN_COMPOSE) build backfill
	docker compose -f $(MAIN_COMPOSE) up -d backfill
	@echo "📜 Tail backfill logs (Ctrl+C to exit)"
	docker logs -f hmm_backfill

# --- Probing many symbols safely --------------------------------------------

probe:
	@echo "🚦 Auto-probing symbols (override with SYMBOLS, PROBE_USDT, MAX_ORDERS_PER_MIN)"
	ENGINE_URL?=http://localhost:8003
	python ops/auto_probe.py --engine $(ENGINE_URL) \
		--symbols "$(SYMBOLS)" \
		--probe-usdt $${PROBE_USDT:-30} \
		--max-orders-per-min $${MAX_ORDERS_PER_MIN:-20} \
		--max-parallel $${MAX_PARALLEL_ORDERS:-3} \
		--cooldown-sec $${PROBE_COOLDOWN_SEC:-90}

stop:
	@echo "🛑 Stopping all services..."
	-docker compose -f $(MAIN_COMPOSE) down
	@if [ -f "$(OBS_COMPOSE)" ]; then \
		docker compose -f $(OBS_COMPOSE) down; \
	fi

restart:
	@echo "♻️  Rebuilding and restarting everything..."
	$(MAKE) stop
	$(MAKE) start

logs:
	@echo "📜 Tail logs (Ctrl+C to exit)"
	docker compose -f $(MAIN_COMPOSE) logs -f --tail=50

status:
	@echo "🩺 Containers:"
	docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep hmm_ || true


# ===== Offline research pipeline ============================================
RANGE ?= 2025-10-01..2025-10-12
SYMS  ?= BTCUSDT,ETHUSDT

init:
	python -m pip install -r requirements.txt ib_insync

# Example single-day download (adjust timestamps)
binance_dl:
	python -c "from adapters.binance_hist import fetch_klines,save_day; import datetime as d; import time; sym='BTCUSDT'; day='2025-10-05'; start=int(time.mktime(time.strptime(day,'%Y-%m-%d'))*1000); end=start+24*3600*1000; df=fetch_klines(sym,start,end); print(save_day(sym, day, df))"

features:
	python pipeline/build_features.py --symbols $(SYMS) --range $(RANGE)

replay:
	python pipeline/replay_situations.py --symbols $(SYMS) --range $(RANGE)

simulate:
	python pipeline/sim_exec.py --symbols $(SYMS) --range $(RANGE) --model quarantine

learn:
	python pipeline/train_bandit_offline.py --pattern "data/outcomes/*.parquet"

report:
	python pipeline/report_backtest.py --range $(RANGE) --pattern "data/outcomes/*.parquet"

offline_all: features replay simulate learn report
