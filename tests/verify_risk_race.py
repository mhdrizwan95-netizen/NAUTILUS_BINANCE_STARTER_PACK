import asyncio
import logging

from engine.config import load_risk_config
from engine.core.event_bus import EventBus
from engine.risk import RiskRails

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_risk_race_condition():
    logger.info("Starting Risk Race Condition Verification...")

    # 1. Setup Components
    import os

    os.environ["TRADING_ENABLED"] = "true"

    # Force enable on disk
    os.makedirs("state", exist_ok=True)
    with open("state/trading_enabled.flag", "w") as f:
        f.write("true")

    bus = EventBus()
    cfg = load_risk_config()
    # cfg.trading_enabled = True  # Removed: FrozenInstanceError

    rails = RiskRails(cfg)

    # Ensure trading is enabled initially
    rails.set_manual_trading_enabled(True)

    # Mock Order Check
    ok, err = rails.check_order(symbol="BTCUSDT", side="BUY", quote=100.0, quantity=None)
    if not ok:
        logger.error(f"Initial check failed. Trading should be enabled. Error: {err}")
        return

    logger.info("Initial state: Trading ENABLED")

    # 2. Wire up the handler (simulating app.py logic)
    async def _handle_risk_violation(evt: dict) -> None:
        if evt.get("action") == "PAUSE":
            rails.set_manual_trading_enabled(False)
            logger.info("Received PAUSE signal. Trading disabled.")

    bus.subscribe("risk.violation", _handle_risk_violation)
    await bus.start()

    # 3. Simulate Risk Violation
    logger.info("Simulating Risk Violation Event...")
    await bus.publish(
        "risk.violation", {"action": "PAUSE", "reason": "test_race_condition", "score": 999.9}
    )

    # Allow event bus to process
    await asyncio.sleep(0.1)

    # 4. Verify Trading is Disabled
    ok, err = rails.check_order(symbol="BTCUSDT", side="BUY", quote=100.0, quantity=None)

    if not ok and err.get("error") == "TRADING_DISABLED":
        logger.info("SUCCESS: Trading was immediately disabled by event.")
        logger.info(f"Error message: {err.get('message')}")
    else:
        logger.error(f"FAILURE: Trading was NOT disabled. Result: {ok}, Err: {err}")
        exit(1)

    await bus.stop()


if __name__ == "__main__":
    asyncio.run(test_risk_race_condition())
