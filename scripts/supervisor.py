#!/usr/bin/env python3
"""
Antigravity Supervisor
======================
The "Immune System" for the Nautilus Trading Node.

Responsibilities:
1. Process Watchdog: Monitors the main trading engine container. Restarts if unhealthy.
2. Latency Watchdog: Parses logs for execution latency > 1000ms. Pauses trading if detected.
3. Circuit Breaker: Monitors daily drawdown. Kills the bot if > 5% loss.
4. Health Heartbeat: Listens to Redis for strategy pulse.

Usage:
    python scripts/supervisor.py [--dry-run]
"""

import asyncio
import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from collections import deque
from pathlib import Path

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

# Configuration
# ==============================================================================
DOCKER_CONTAINER_NAME = os.getenv("TRADING_CONTAINER_NAME", "hmm_engine_binance")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
LOG_FILE = Path("engine/logs/nautilus.log")
MAX_LATENCY_MS = 1000
MAX_DRAWDOWN_PCT = 0.05
HEARTBEAT_TIMEOUT_SEC = 60
CHECK_INTERVAL_SEC = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SUPERVISOR] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("supervisor.log"),
    ],
)
logger = logging.getLogger("Supervisor")


class Supervisor:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        if redis:
            self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        else:
            if not dry_run:
                print("❌ Redis required for live run")
                sys.exit(1)
            self.redis = None # type: ignore
        self.last_heartbeat = time.time()
        self.running = True
        self.latency_buffer = deque(maxlen=20)
        self.daily_high_water_mark = 0.0

    async def start(self):
        """Main event loop."""
        logger.info(f"🚀 Supervisor starting... [Dry Run: {self.dry_run}]")
        logger.info(f"Targets: Container={DOCKER_CONTAINER_NAME}, Log={LOG_FILE}")
        
        # Start concurrent tasks
        tasks = [
            self.monitor_heartbeat(),
            self.monitor_logs(),
            self.monitor_container(),
            self.monitor_drawdown(),
        ]
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Supervisor shutting down...")
        finally:
            await self.redis.close()

    async def monitor_heartbeat(self):
        """Subscribes to Redis heartbeat channel to verify strategy is alive."""
        if not self.redis:
            logger.info("💓 Heartbeat monitor disabled (No Redis)")
            return

        pubsub = self.redis.pubsub()
        await pubsub.subscribe("heartbeat")
        
        logger.info("💓 Heartbeat monitor active")
        
        try:
            while self.running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    self.last_heartbeat = time.time()
                
                # Check for timeout
                time_since_beat = time.time() - self.last_heartbeat
                if time_since_beat > HEARTBEAT_TIMEOUT_SEC:
                    logger.error(f"❌ Heartbeat missing for {time_since_beat:.1f}s!")
                    await self._restart_container(reason="Heartbeat Timeout")
                    self.last_heartbeat = time.time()  # Reset after restart attempt
                
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Heartbeat monitor failed: {e}")

    async def monitor_logs(self):
        """Tails the nautilus log file for latency warnings."""
        if not LOG_FILE.exists():
            logger.warning(f"⚠️ Log file not found at {LOG_FILE}. Waiting...")
        
        # Simple tail implementation
        f = None
        while self.running:
            if not f and LOG_FILE.exists():
                f = open(LOG_FILE, "r")
                f.seek(0, os.SEEK_END)
            
            if f:
                line = f.readline()
                if line:
                    await self._analyze_log_line(line)
                else:
                    await asyncio.sleep(0.1)
            else:
                await asyncio.sleep(5)

    async def _analyze_log_line(self, line: str):
        """Analyzes a single log line for danger signals."""
        if "Order execution latency" in line:
            # Example: "Order execution latency: 1250ms"
            try:
                # Extract latency value - implementation depends on exact log format
                # Assuming format "... latency: 1250ms"
                parts = line.split("latency")
                if len(parts) > 1:
                    ms_part = parts[1].split("ms")[0].strip().replace(":", "").replace("=", "")
                    latency = float(ms_part)
                    
                    if latency > MAX_LATENCY_MS:
                        logger.warning(f"🐢 High Latency detected: {latency}ms")
                        await self._trigger_latency_circuit_breaker()
            except Exception:
                pass
        
        if "WebSocket disconnect" in line:
            logger.warning("🔌 WebSocket disconnect detected")

    async def _trigger_latency_circuit_breaker(self):
        """Pauses trading if latency is too high."""
        logger.warning("🛑 Triggering Latency Circuit Breaker (Pause Trading)")
        if not self.dry_run:
            # Send pause command via Redis or API
            # Ideally we use the ops API, but here we can set a flag in Redis
            # capable of being read by the strategy
            await self.redis.set("TRADING_ENABLED", "false")
            logger.info("Sent TRADING_ENABLED=false to Redis")

    async def monitor_container(self):
        """Checks if Docker container is running."""
        while self.running:
            is_running = await self._check_container_status()
            if not is_running:
                logger.error("💀 Container is DOWN!")
                await self._restart_container(reason="Container Crash")
            await asyncio.sleep(CHECK_INTERVAL_SEC)

    async def _check_container_status(self) -> bool:
        """Returns True if container is running."""
        if self.dry_run:
            return True
            
        try:
            proc = await asyncio.create_subprocess_shell(
                f"docker inspect -f '{{{{.State.Running}}}}' {DOCKER_CONTAINER_NAME}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            return stdout.decode().strip() == "true"
        except Exception as e:
            logger.error(f"Docker check failed: {e}")
            return False

    async def _restart_container(self, reason: str):
        """Restarts the trading node."""
        logger.warning(f"🔄 Restarting container due to: {reason}")
        if self.dry_run:
            logger.info("[DRY RUN] Would restart container now.")
            return

        try:
            cmd = f"docker restart {DOCKER_CONTAINER_NAME}"
            proc = await asyncio.create_subprocess_shell(cmd)
            await proc.wait()
            logger.info("✅ Restart command sent.")
            self.last_heartbeat = time.time() # Reset heartbeat timer
        except Exception as e:
            logger.error(f"Restart failed: {e}")

    async def monitor_drawdown(self):
        """Checks account balance and triggers hard stop if drawdown > limit."""
        # Note: In a real implementation, this would query the Ops API or Binance API.
        # For this starter pack implementation, we will query the Ops API endpoint.
        OPS_API_URL = "http://localhost:8002/metrics" # Assuming metrics endpoint has equity
        
        while self.running:
            # Placeholder for actual API call
            # For now, we stub this effectively, or check a Redis key where the engine publishes equity
            try:
                # Assuming engine publishes equity to Redis for easier access
                equity_str = await self.redis.get("metric:equity")
                if equity_str:
                    equity = float(equity_str)
                    
                    # Update HWM
                    if equity > self.daily_high_water_mark:
                        self.daily_high_water_mark = equity
                    
                    # Check Drawdown
                    if self.daily_high_water_mark > 0:
                        dd = (self.daily_high_water_mark - equity) / self.daily_high_water_mark
                        if dd > MAX_DRAWDOWN_PCT:
                            logger.critical(f"📉 HARD STOP TRIGGERED! Drawdown: {dd*100:.2f}% > {MAX_DRAWDOWN_PCT*100}%")
                            await self._emergency_shutdown()
            except Exception as e:
                pass # redis might be empty initially
                
            await asyncio.sleep(60)

    async def _emergency_shutdown(self):
        """Gracefully shuts down everything and prevents restart."""
        logger.critical("☠️ INITIATING EMERGENCY SHUTDOWN")
        if not self.dry_run:
            await self.redis.set("TRADING_ENABLED", "false")
            cmd = f"docker stop {DOCKER_CONTAINER_NAME}"
            await asyncio.create_subprocess_shell(cmd)
            # Kill supervisor too so it doesn't restart it
            sys.exit(1)

def handle_signal(sig, frame):
    logger.info("Received stop signal")
    sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Antigravity Supervisor")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without executing")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    supervisor = Supervisor(dry_run=args.dry_run)
    
    try:
        asyncio.run(supervisor.start())
    except KeyboardInterrupt:
        pass
