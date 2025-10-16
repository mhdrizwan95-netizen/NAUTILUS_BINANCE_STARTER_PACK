# Developer Guide

## Environment

- Python ≥ 3.10
- FastAPI + HTTPX + Prometheus Client
- Docker / Docker Compose
- pytest + pytest-asyncio for tests

Install:
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Branching Convention

Type	Prefix	Example
Feature	feat/	feat/capital-allocator
Fix	fix/	fix/risk-rails-validation
Docs	docs/	docs/system-overview
Refactor	ref/	ref/unify-logging
Test	test/	test/add-canary-validation

## Development Workflow

1. **Code:** Implement feature/fix
2. **Test:** Add tests, run suite
3. **Integrate:** Build docker-compose
4. **Validate:** Test end-to-end
5. **Document:** Update docs/ if needed
6. **Review:** Create PR with description

### Local Development
```bash
# Start just OPS for development
docker compose up ops --build

# Run tests in watch mode
pytest-watch tests/

# Debug specific component
python -m ops.capital_allocator  # Run standalone
```

### Testing Strategy

#### Unit Tests
- Cover all major functions (allocators, routers, evaluators)
- Mock external dependencies (HTTPX, file I/O)
- Test edge cases and error conditions

#### Integration Tests
- OPS ⇄ Engine API communication
- Prometheus metric collection/scraping
- Database persistence and recovery
- Docker container networking

#### End-to-End Tests
- Complete signal → execution → measurement flow
- Multi-container docker-compose scenarios
- Performance/load testing

### Key Test Coverage Areas

```bash
pytest tests/test_capital_allocation.py -v  # Allocation logic
pytest tests/test_canary_weights.py -v      # Routing weights
pytest tests/test_strategy.py -v            # Model behavior
pytest tests/test_risk_rails.py -v          # Risk enforcement
```

## Code Style

### Python Standards
```python
# Use async for all I/O
async def fetch_metrics():
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)

# Structured error responses
return {
    "error": "validation_failed",
    "code": "INVALID_QUOTE",
    "message": "Quote exceeds allocation",
    "details": {"requested": 1000, "available": 500}
}

# Atomic file operations
temp_path = target.with_suffix('.tmp')
try:
    temp_path.write_text(json.dumps(data, indent=2))
    temp_path.replace(target)  # Atomic move
except Exception:
    temp_path.unlink(missing_ok=True)  # Clean up on error
```

### Logging Patterns
```python
import logging
logger = logging.getLogger(__name__)

# Info for normal operations
logger.info(f"[COMPONENT] Model {model_id} promoted to {weight:.1%}")

# Warning for recoverable issues
logger.warning(f"[COMPONENT] Metrics fetch failed, using cache")

# Error for serious problems
logger.error(f"[COMPONENT] Critical allocation failure: {e}")
```

### Environment Configuration
```python
# Always use environment variables for secrets/config
METRICS_URL = os.getenv("OPS_METRICS_URL", "http://localhost:8002/metrics")
API_TIMEOUT = float(os.getenv("API_TIMEOUT_SEC", "5.0"))

# Never hardcode paths - use pathlib for cross-platform
CONFIG_PATH = Path("ops") / "config.json"
LOGS_DIR = Path("logs") / datetime.now().strftime("%Y-%m-%d")
LOGS_DIR.mkdir(parents=True, exist_ok=True)
```

Ops workers default to two Uvicorn processes (`OPS_WORKERS` in `.env`). When adding file writes make sure the non-root user can modify the destination and prefer atomic `Path.replace()` calls as shown above.

## Architecture Guidelines

### Component Isolation
- **Controls:** Never import from ops/ into engine/ (directional dependency)
- **Events:** Use event bus for cross-component communication
- **Config:** Environment variables with JSON configs for complex structures
- **Data:** Append-only JSONL logs, never mutate existing records

### Error Handling
- **Validate inputs** at all API boundaries
- **Graceful degradation** when dependencies fail
- **Circuit breakers** for external service failures
- **Recovery procedures** for state corruption

### Performance Considerations
- **Async everywhere** - never block on I/O
- **Batching** - group similar operations when possible
- **Caching** - short-lived caches for frequent data
- **Pagination** - for large result sets
- **Memory limits** - implement bounds on in-memory collections

## Instrumentation

### Prometheus Metrics
```python
from prometheus_client import Counter, Gauge, Histogram
from ops.prometheus import REGISTRY

# Multi-worker safe metrics – always register against REGISTRY.
SIGNALS_ROUTED = Counter(
    "signals_routed_total",
    "Total signals processed",
    ["model"],
    registry=REGISTRY,
)

ORDERS_SUBMITTED = Counter(
    "orders_submitted_total",
    "Orders sent to engine",
    ["venue"],
    registry=REGISTRY,
)

ALLOCATED_CAPITAL = Gauge(
    "allocated_capital_usd",
    "Total capital allocated",
    ["model"],
    registry=REGISTRY,
    multiprocess_mode="max",
)

SIGNAL_LATENCY = Histogram(
    "signal_latency_seconds",
    "End-to-end signal processing time",
    registry=REGISTRY,
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
)

# Usage
SIGNALS_ROUTED.labels(model="canary_v2").inc()
ALLOCATED_CAPITAL.labels(model="canary_v2").set(15432.50)
```

The helper in `ops/prometheus.py` creates a per-process `CollectorRegistry`, attaches `multiprocess.MultiProcessCollector`, and provides `render_latest()` for the `/metrics` endpoint. Always import `REGISTRY` from there instead of relying on the global default registry.

### Health Checks
```python
@app.get("/health")
def health():
    # System health
    services_ok = check_databases() and check_exchanges()

    # Data freshness
    metrics_fresh = (time.time() - last_metrics_update) < 300

    return {
        "status": "healthy" if services_ok else "degraded",
        "checks": {
            "services": services_ok,
            "metrics_fresh": metrics_fresh,
            "last_update": last_metrics_update
        }
    }
```

## Security Practices

### API Access Control
```python
def verify_token(token: str) -> bool:
    # Never log raw tokens in production
    expected = os.getenv("OPS_API_TOKEN")
    return token and token == expected

@app.post("/admin/restart")
def admin_action(request: Request):
    if not verify_token(request.headers.get("X-OPS-TOKEN")):
        raise HTTPException(401, "Invalid token")
    # Proceed with privileged operation
```

### Data Validation
```python
from pydantic import BaseModel, validator

class StrategyWeights(BaseModel):
    weights: Dict[str, float]

    @validator('weights')
    def validate_weights(cls, v):
        if abs(sum(v.values()) - 1.0) > 0.001:
            raise ValueError("Weights must sum to 1.0")
        return v
```

## CI/CD Pipeline

### Pre-commit Checks
```yaml
# .pre-commit-config.yaml
repos:
- repo: https://github.com/psf/black
  rev: stable
  hooks:
  - id: black
- repo: https://github.com/pycqa/flake8
  rev: latest
  hooks:
  - id: flake8
- repo: https://github.com/pre-commit/mirrors-mypy
  rev: latest
  hooks:
  - id: mypy
```

### CI Stages
1. **Lint:** `flake8` and `mypy` must pass
2. **Unit:** `pytest -xvs --cov=nautilus --cov-report=html`
3. **Integration:** Docker-compose test scenario
4. **Security:** Static analysis for vulnerabilities
5. **Build:** Docker image built and tagged

### Deployment Safety
- **Feature Flags:** New features can be disabled instantly
- **Canary Releases:** All model updates go through canary process
- **Rollback Scripts:** Automated rollback procedures
- **Database Migrations:** Versioned schema changes

## Debugging Techniques

### Local Debugging
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Debug specific component
PYTHONPATH=. python -c "
import ops.capital_allocator as ca
print(ca.get_model_quota('test_model'))
"

# Interactive debugging
docker compose exec ops python
>>> import ops.strategy_router
>>> # Debug commands here
```

### Remote Debugging
```bash
# Enable profiler
PYTHONDONTWRITEBYTECODE=1 python -m cProfile -o profile.prof ops/ops_api.py

# Analyze bottlenecks
import pstats
p = pstats.Stats('profile.prof')
p.print_stats()
```

## Extension Points

### Adding New Strategies
1. Implement strategy in `strategies/new_strategy/`
2. Add to strategy registry: `ops/strategy_registry.json`
3. Update capital policy enabled list
4. Add backtesting in `backtests/`
5. Test canary promotion process

### Adding New Venues
1. Create venue adapter: `engine/adapters/new_venue.py`
2. Add configuration to `ops/env.example`
3. Update docker-compose.yml
4. Add health checks and monitoring
5. Test venue-specific risk rails

### Adding New Metrics
1. Define metric in Prometheus config
2. Add instrumentation in relevant components
3. Update dashboard if needed
4. Add alerting rules if required

## Performance Profiling

```python
import cProfile
import asyncio

async def profile_allocation():
    pr = cProfile.Profile()
    pr.enable()
    await simulate_allocation_cycle()
    pr.disable()
    pr.print_stats(sort='cumulative')
```

## Documentation Standards

### Code Documentation
```python
def complex_function(param1: ComplexType, param2: int) -> ComplexReturn:
    """
    Perform complex allocation calculation.

    This function implements Sharpe-based capital reallocation across
    multiple models while respecting cooldown periods and bounds.

    Args:
        param1: Description of complex parameter
        param2: Simple integer parameter

    Returns:
        ComplexReturn: Detailed description of return structure

    Raises:
        ValueError: When allocation violates constraints
        RuntimeError: When external dependencies unavailable

    Example:
        >>> result = complex_function(ComplexType(), 42)
        >>> assert result.total_allocated > 0
    """
```

### API Documentation
```python
@router.post("/strategy/allocate")
async def allocate_capital(allocation: AllocationRequest):
    """
    Manually trigger capital reallocation.

    This endpoint forces an immediate capital redistribution cycle
    regardless of cooldown timers, useful for emergency adjustments.

    Args:
        allocation: Parameters for allocation override

    Returns:
        dict: Allocation results with new quota assignments

    Raises:
        HTTPException: 403 if manual allocation disabled
                       500 if allocation calculation fails
    """
```

## Troubleshooting Development

### Common Issues

**Import Errors:**
- Ensure `PYTHONPATH=.` for local development
- Check that all dependencies are installed
- Verify Docker container rebuilt after code changes

**Permission Errors:**
- Use `sudo` for system-level operations only
- Ensure Docker daemon allows container access to files
- Check that logs directories are writable

**Async Errors:**
- Never call async functions from sync context without `asyncio.run()`
- Use `asyncio.gather()` for concurrent operations
- Ensure event loops aren't nested

**Metric Discrepancies:**
- Compare raw Prometheus metrics with dashboard aggregations
- Use `curl http://localhost:9090/api/v1/query?query=metric_name` for direct inspection
- Verify metric labels are correctly set
