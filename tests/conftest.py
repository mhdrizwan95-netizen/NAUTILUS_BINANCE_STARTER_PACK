import os

DEFAULT_OPS_TOKEN = "test-ops-token-1234567890"
os.environ.setdefault("OPS_API_TOKEN", DEFAULT_OPS_TOKEN)
os.environ.setdefault("TRADING_ENABLED", "true")
os.environ.setdefault("DRY_RUN", "false")
