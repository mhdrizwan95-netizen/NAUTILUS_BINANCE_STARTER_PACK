# =============================================================================
# Nautilus Trading Stack — Makefile (Exporter/Trader split + Observability)
# =============================================================================
# `make help` for a quick tour.
# =============================================================================

# ---- Configurable knobs ------------------------------------------------------
PYTHON                ?= python3
COMPOSE               ?= docker compose
OBS_COMPOSE           ?= docker compose -f ops/observability/docker-compose.observability.yml
COMPOSE_BUILD_FLAGS   ?= --progress=plain

# Service names (as in docker-compose.yml)
ENGINE_EXPORTER_SVC   ?= engine_binance_exporter
ENGINE_TRADER_SVC     ?= engine_binance
EXECUTOR_SVC          ?= executor
OPS_SVC               ?= ops
PROM_SVC              ?= prometheus
GRAFANA_SVC           ?= grafana

# Host endpoints
PROM_URL              ?= http://localhost:9090
GRAFANA_URL           ?= http://localhost:3000
ENGINE_TRADER_URL     ?= http://localhost:8003          # submit orders here
ENGINE_EXPORTER_URL   ?= http://localhost:9103          # read-only metrics here

# Test-order defaults (override with: make order ORDER_QUOTE=50 ORDER_SYMBOL=ETHUSDT.BINANCE)
ORDER_SYMBOL          ?= BTCUSDT.BINANCE
ORDER_SIDE            ?= BUY
ORDER_QUOTE           ?= 25

# -----------------------------------------------------------------------------
# Meta / Help
# -----------------------------------------------------------------------------
.PHONY: help
help:
	@echo ""
	@echo "Nautilus Trading Stack — handy targets"
	@echo "--------------------------------------------------------------------"
	@echo "Core lifecycle:"
	@echo "  make build                 # build all core images"
	@echo "  make up-core               # start universe, situations, screener, ops, engine"
	@echo "  make up-ml                 # start ML/backtest pipeline (profile: ml)"
	@echo "  make up-exporter           # start the Binance exporter (role=exporter)"
	@echo "  make up-trader             # start the Binance trader (role=trader)"
	@echo "  make up-obs                # start Prometheus + Grafana"
	@echo "  make ps                    # show important containers"
	@echo ""
	@echo "Observability & health:"
	@echo "  make smoke-exporter        # verify exporter metrics & accounting identity"
	@echo "  make smoke-prom            # verify Prom targets and freshness"
	@echo "  make validate-obs          # validate observability queries"
	@echo "  make telegram-ping         # send a Telegram test message (DNS-fallback)"
	@echo "  make grafana-restart       # restart Grafana to reload dashboards"
	@echo "  make prom-reload           # hot-reload Prometheus config"
	@echo ""
	@echo "Trading ops:"
	@echo "  make order                 # submit a small market order (symbol/side/quote vars)"
	@echo "  make executor-up           # start storm-proof executor"
	@echo "  make executor-down         # stop executor"
	@echo ""
	@echo "One-command autopilot:"
	@echo "  make autopilot             # full stack up + health checks + observability"
	@echo "  make autopilot-observe     # just start Prometheus + Grafana"
	@echo "  make autopilot-status      # quick health snapshot"
	@echo ""
	@echo "Maintenance:"
	@echo "  make restart-exporter      # restart exporter only"
	@echo "  make restart-trader        # restart trader only"
	@echo "  make down                  # stop core services (keeps volumes)"
	@echo "  make down-all              # stop core + observability"
	@echo ""
	@echo "CI helpers:"
	@echo "  make lint                  # hadolint Dockerfiles (if installed)"
	@echo "  make test                  # run Python tests (and frontend unit tests if npm present)"
	@echo "  make image                 # build main Dockerfile image"
	@echo "  make push REGISTRY=org IMG=nautilus TAG=dev   # push image"
	@echo ""

# -----------------------------------------------------------------------------
# Build & Core lifecycle
# -----------------------------------------------------------------------------
.PHONY: build
build:
	$(COMPOSE) build $(COMPOSE_BUILD_FLAGS)

.PHONY: up-core
up-core:
	@echo "🚀 Starting core services (situations, universe, screener, ops, engine)…"
	$(COMPOSE) up -d situations universe screener $(OPS_SVC) engine_binance

.PHONY: up-ml
up-ml:
	@echo "🧪 Starting ML/backtest pipeline (profile: ml)…"
	$(COMPOSE) --profile ml up -d data_ingester ml_service ml_scheduler param_controller backtest_runner data_backfill

.PHONY: up-exporter
up-exporter:
	@echo "🚀 Starting Binance exporter (read-only metrics @ $(ENGINE_EXPORTER_URL))…"
	$(COMPOSE) up -d $(ENGINE_EXPORTER_SVC)

.PHONY: up-trader
up-trader:
	@echo "🚀 Starting Binance trader (order API @ $(ENGINE_TRADER_URL))…"
	$(COMPOSE) up -d $(ENGINE_TRADER_SVC)

.PHONY: up-obs
up-obs:
	@echo "📊 Starting observability (Prometheus + Grafana)…"
	$(OBS_COMPOSE) up -d $(PROM_SVC) $(GRAFANA_SVC)

.PHONY: ps
ps:
	$(COMPOSE) ps
	$(OBS_COMPOSE) ps || true

# -----------------------------------------------------------------------------
# Observability / health checks
# -----------------------------------------------------------------------------
.PHONY: smoke-exporter
smoke-exporter:
	@echo "🔎 Exporter core gauges:"
	@curl -fsS $(ENGINE_EXPORTER_URL)/metrics | egrep '^(equity_usd|cash_usd|market_value_usd|metrics_heartbeat|snapshot_id)' || true
	@echo "🔎 Accounting residual (should be 0):"
	@curl -fsS -G --data-urlencode 'query=abs(equity_usd{job="engine_binance"}-(cash_usd{job="engine_binance"}+market_value_usd{job="engine_binance"}))' $(PROM_URL)/api/v1/query | jq -r '.data.result[]?.value[1]' || true
	@echo "🔎 Heartbeat lag (s) — expect <15:"
	@curl -fsS -G --data-urlencode 'query=time()-metrics_heartbeat{job="engine_binance_exporter"}' $(PROM_URL)/api/v1/query | jq -r '.data.result[]?.value[1]' || true

.PHONY: smoke-prom
smoke-prom:
	@echo "🔎 Prom targets (UP expected for exporter/trader if running):"
	@curl -fsS $(PROM_URL)/api/v1/targets | jq '.data.activeTargets[] | {job:.labels.job, url:.scrapeUrl, health:.health, lastError:.lastError}'

.PHONY: grafana-restart
grafana-restart:
	$(OBS_COMPOSE) restart $(GRAFANA_SVC)

.PHONY: prom-reload
prom-reload:
	@curl -fsS -X POST $(PROM_URL)/-/reload && echo "Prometheus reload requested."

.PHONY: validate-obs
validate-obs:
	@echo "🔍 Validating observability pipeline queries..."
	cd ops/observability && ./validate_obs.sh

# -----------------------------------------------------------------------------
# Notifications / Telegram
# -----------------------------------------------------------------------------
.PHONY: telegram-ping
telegram-ping:
	@scripts/telegram_ping.sh "Telegram wired ✅"

# -----------------------------------------------------------------------------
# Trading ops
# -----------------------------------------------------------------------------
.PHONY: order
order:
	@echo "🧪 Submitting market order: $(ORDER_SYMBOL) $(ORDER_SIDE) quote=$(ORDER_QUOTE)"
	@curl -fsS -X POST $(ENGINE_TRADER_URL)/orders/market \
	  -H 'Content-Type: application/json' \
	  -d '{"symbol":"$(ORDER_SYMBOL)","side":"$(ORDER_SIDE)","quote":$(ORDER_QUOTE)}' | jq . || true

.PHONY: executor-up
executor-up:
	@echo "🧠 Starting executor (storm-proof)…"
	$(COMPOSE) up -d $(EXECUTOR_SVC)

.PHONY: executor-down
executor-down:
	$(COMPOSE) stop $(EXECUTOR_SVC)

# -----------------------------------------------------------------------------
# Maintenance
# -----------------------------------------------------------------------------
.PHONY: restart-exporter restart-trader
restart-exporter:
	$(COMPOSE) up -d --no-deps --force-recreate $(ENGINE_EXPORTER_SVC)

restart-trader:
	$(COMPOSE) up -d --no-deps --force-recreate $(ENGINE_TRADER_SVC)

.PHONY: down down-all
down:
	$(COMPOSE) down

down-all:
	$(COMPOSE) down || true
	$(OBS_COMPOSE) down || true

# -----------------------------------------------------------------------------
# CI helpers
# -----------------------------------------------------------------------------
.PHONY: lint test image push ci
lint:
	@which hadolint >/dev/null 2>&1 && hadolint Dockerfile || echo "hadolint not installed; skipping root Dockerfile"
	@which hadolint >/dev/null 2>&1 && hadolint services/ml_service/Dockerfile || true
	@which hadolint >/dev/null 2>&1 && hadolint services/data_ingester/Dockerfile || true
	@which hadolint >/dev/null 2>&1 && hadolint services/param_controller/Dockerfile || true
	@which hadolint >/dev/null 2>&1 && hadolint services/backtest_suite/Dockerfile || true
	@echo "lint done"

test:
	@$(PYTHON) -m pytest -q --maxfail=1
	@if command -v npm >/dev/null 2>&1; then \
	  echo "Running frontend unit tests"; \
	  cd frontend && npm ci && npm run test -- --run; \
	else echo "npm not found; skipping frontend tests"; fi

image:
	@docker build -t $(IMG:-=nautilus):$(TAG:-=dev) -f Dockerfile .

push:
	@if [ -z "$(REGISTRY)" ]; then echo "REGISTRY is required"; exit 1; fi
	@docker tag $(IMG:-=nautilus):$(TAG:-=dev) $(REGISTRY)/$(IMG:-=nautilus):$(TAG:-=dev)
	@docker push $(REGISTRY)/$(IMG:-=nautilus):$(TAG:-=dev)

ci: lint test

.PHONY: docker-prune prune-ml-volumes
docker-prune:
	@echo "🧹 Pruning unused images, containers, networks, and dangling volumes…"
	docker system prune -af
	docker builder prune -af || true

prune-ml-volumes:
	@echo "🗑  Removing ML/backtest named volumes (this deletes stored datasets/models/results)…"
	-@docker volume rm -f nautilus_binance_starter_pack_ml_data_volume 2>/dev/null || true
	-@docker volume rm -f nautilus_binance_starter_pack_ml_models_volume 2>/dev/null || true
	-@docker volume rm -f nautilus_binance_starter_pack_ml_shared_volume 2>/dev/null || true
	-@docker volume rm -f nautilus_binance_starter_pack_backtest_research_volume 2>/dev/null || true
	-@docker volume rm -f nautilus_binance_starter_pack_backtest_results_volume 2>/dev/null || true

# -----------------------------------------------------------------------------
# Logs (convenience)
# -----------------------------------------------------------------------------
.PHONY: logs-exporter logs-trader logs-executor
logs-exporter:
	$(COMPOSE) logs -f --tail=200 $(ENGINE_EXPORTER_SVC)

logs-trader:
	$(COMPOSE) logs -f --tail=200 $(ENGINE_TRADER_SVC)

logs-executor:
	$(COMPOSE) logs -f --tail=200 $(EXECUTOR_SVC)
# -----------------------------------------------------------------------------
# 🚀 One-Command Autopilot: full stack up + trading enabled
# -----------------------------------------------------------------------------
.PHONY: autopilot
autopilot:
	@echo "=============================================================="
	@echo " 🧠  LAUNCHING FULL AUTONOMOUS TRADING STACK"
	@echo "=============================================================="
	@echo "1️⃣  Building images (if needed)..."
	$(COMPOSE) build $(COMPOSE_BUILD_FLAGS)
	@echo "2️⃣  Starting core services (universe, screener, ops, engines)..."
	$(COMPOSE) up -d situations universe screener ops engine_binance engine_binance_exporter
	$(COMPOSE) --profile ml up -d data_ingester ml_service ml_scheduler param_controller backtest_runner data_backfill || true
	@echo "3️⃣  Starting executor..."
	$(COMPOSE) up -d $(EXECUTOR_SVC)
	@echo "4️⃣  Health checks..."
	@echo " - Waiting for exporter metrics on :9103..."
	@bash -c 'for i in {1..30}; do curl -fsS http://localhost:9103/metrics >/dev/null 2>&1 && break || sleep 1; done'
	@echo " - Waiting for trader HTTP on :8003..."
	@bash -c 'for i in {1..30}; do curl -fsS http://localhost:8003/health >/dev/null 2>&1 && break || sleep 1; done'
	@echo " - Waiting for ML service health on :8015..."
	@bash -c 'for i in {1..30}; do curl -fsS http://localhost:8015/health >/dev/null 2>&1 && break || sleep 1; done'
	@echo "5️⃣  Starting observability (Prometheus + Grafana)..."
	$(OBS_COMPOSE) up -d $(PROM_SVC) $(GRAFANA_SVC)
	@echo "✅  All systems online. Waiting 10s for heartbeats..."
	sleep 10
	@echo "🔎  Checking exporter metrics health:"
	@curl -fsS -G --data-urlencode 'query=time()-metrics_heartbeat{job="engine_binance_exporter"}' $(PROM_URL)/api/v1/query | jq -r '.data.result[]?.value[1]' || true
	@echo "=============================================================="
	@echo " 🏁  AUTONOMOUS TRADING LIVE!"
	@echo " - Exporter @ $(ENGINE_EXPORTER_URL)"
	@echo " - Trader   @ $(ENGINE_TRADER_URL)"
	@echo " - Grafana  @ $(GRAFANA_URL) (dashboard: Command Center)"
	@echo "=============================================================="

.PHONY: autopilot-observe
autopilot-observe:
	@echo "🔭 Starting observability (Prometheus + Grafana)..."
	@docker network create nautilus_trading_network 2>/dev/null || true
	docker compose -f ops/observability/docker-compose.observability.yml up -d prometheus grafana
	@echo "• Prometheus:  http://localhost:9090"
	@echo "• Grafana:     http://localhost:3000"

.PHONY: autopilot-status
autopilot-status:
	@echo "🩺 Exporter metrics sample:" && curl -fsS http://localhost:9103/metrics | egrep '^(equity_usd|cash_usd|market_value_usd|metrics_heartbeat|snapshot_id)' || true
	@echo "🧪 Trader health:" && curl -fsS http://localhost:8003/health || true
	@echo "📡 Prom targets (if running):" && curl -fsS http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job:.labels.job, url:.scrapeUrl, health:.health}' || true

.PHONY: autopilot-paper
autopilot-paper:
	$(MAKE) up-core
	$(MAKE) up-obs
	sleep 2
	curl -s -X POST http://localhost:8000/governance/flags \
	  -H 'Content-Type: application/json' \
	  -d '{"AUTOPILOT_ENABLED": true, "PAPER_TRADING": true, "AUTOPILOT_MIN_CONF": 0.55}' >/dev/null || true
