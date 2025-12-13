from __future__ import annotations

import logging
import time
import json
import httpx
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from engine.config import get_settings
from engine.config.env import env_bool, env_float, env_int, env_str
from engine.core.market_resolver import resolve_market_choice
from . import policy_hmm

try:
    import tomllib
except ImportError:
    try:
        import toml as tomllib
    except ImportError:
        tomllib = None

logger = logging.getLogger("engine.deepseek")

DEEPSEEK_DEFAULTS = {
    "DEEPSEEK_ENABLED": "false",
    "DEEPSEEK_MODEL": "deepseek-chat", # Default to Cloud ID
    "DEEPSEEK_API_URL": "https://api.deepseek.com", # Default to Cloud URL
    "DEEPSEEK_API_KEY": "", # Required for Cloud
    "DEEPSEEK_CONFIDENCE_THRESHOLD": "0.7",
    "DEEPSEEK_POLL_INTERVAL": "300",  # 5 minutes
    "DEEPSEEK_LOOKBACK_BARS": "50",
    "DEEPSEEK_RISK_PCT": "0.02",
}

@dataclass
class DeepSeekConfig:
    enabled: bool
    model: str
    api_url: str
    api_key: str
    confidence_threshold: float
    poll_interval: int
    lookback_bars: int
    risk_pct: float

def load_deepseek_config() -> DeepSeekConfig:
    # Try loading from toml first for overrides
    toml_cfg = {}
    if tomllib:
        try:
            with open("config/live_strategy.toml", "rb") as f:
                data = tomllib.load(f)
                toml_cfg = data.get("deepseek_v2", {})
        except Exception:
            pass

    return DeepSeekConfig(
        enabled=env_bool("DEEPSEEK_ENABLED", DEEPSEEK_DEFAULTS["DEEPSEEK_ENABLED"]),
        model=env_str("DEEPSEEK_MODEL", DEEPSEEK_DEFAULTS["DEEPSEEK_MODEL"]),
        api_url=env_str("DEEPSEEK_API_URL", DEEPSEEK_DEFAULTS["DEEPSEEK_API_URL"]),
        api_key=toml_cfg.get("deepseek_api_key") or env_str("DEEPSEEK_API_KEY", DEEPSEEK_DEFAULTS["DEEPSEEK_API_KEY"]),
        confidence_threshold=toml_cfg.get("confidence_threshold") or env_float("DEEPSEEK_CONFIDENCE_THRESHOLD", DEEPSEEK_DEFAULTS["DEEPSEEK_CONFIDENCE_THRESHOLD"]),
        poll_interval=env_int("DEEPSEEK_POLL_INTERVAL", DEEPSEEK_DEFAULTS["DEEPSEEK_POLL_INTERVAL"]),
        lookback_bars=env_int("DEEPSEEK_LOOKBACK_BARS", DEEPSEEK_DEFAULTS["DEEPSEEK_LOOKBACK_BARS"]),
        risk_pct=toml_cfg.get("risk_pct") or env_float("DEEPSEEK_RISK_PCT", DEEPSEEK_DEFAULTS["DEEPSEEK_RISK_PCT"]),
    )

class DeepSeekStrategyModule:
    """
    Integrates DeepSeek LLM for semantic market analysis and trading decisions.
    Supports both Cloud API (OpenAI-compatible) and Local Inference (Ollama).
    """
    def __init__(self, cfg: DeepSeekConfig):
        self.cfg = cfg
        self.enabled = cfg.enabled
        self._last_poll = defaultdict(float)
        self._client = httpx.AsyncClient(timeout=60.0)
        self._queue = asyncio.Queue(maxsize=10) # Drop oldest if full? No, maxsize blocks or raises full. 
        # Actually better to drop old ticks if we are busy.
        
        # Determine mode
        self.is_local = "localhost" in self.cfg.api_url or "127.0.0.1" in self.cfg.api_url
        
        # Telemetry State
        self.last_confidence = 0.0
        self.last_reasoning = "Initializing..."
        
        logger.info(f"DeepSeek Strategy initialized. Mode: {'LOCAL' if self.is_local else 'CLOUD'}")
        
        # Start Worker
        if self.enabled:
            loop = asyncio.get_running_loop()
            loop.create_task(self._worker_loop())

    async def handle_tick(self, symbol: str, price: float, ts: float) -> None:
        """
        Non-blocking tick handler.
        Pushes market state to the worker queue.
        """
        if not self.enabled:
            return
        
        now = time.time()
        # Rate Limit Enqueueing (Don't flood queue)
        if now - self._last_poll[symbol] < self.cfg.poll_interval:
            return

        self._last_poll[symbol] = now
        
        try:
            # If queue full, we skip this tick (it's fine, we are busy thinking)
            self._queue.put_nowait({
                "symbol": symbol,
                "price": price,
                "ts": ts
            })
        except asyncio.QueueFull:
            pass

    async def _worker_loop(self):
        """
        Background worker that processes ticks one by one.
        This provides the "Thinking Time" without blocking the Event Loop.
        """
        logger.info("DeepSeek Worker Loop Started")
        from engine.services.telemetry_broadcaster import BROADCASTER
        from engine.core.event_bus import BUS
        from .prompt_builder import PromptBuilder
        
        while True:
            try:
                # Wait for next job
                job = await self._queue.get()
                symbol = job["symbol"]
                price = job["price"]
                
                # 1. Fetch Context
                klines = await self._fetch_klines(symbol.split(".")[0], "1h", self.cfg.lookback_bars)
                if not klines:
                    self._queue.task_done()
                    continue
                
                regime = policy_hmm.get_regime(symbol.split(".")[0])
                
                # 2. Build Prompt
                market_data = {
                    "price": price,
                    "recent_closes": [float(k[4]) for k in klines],
                    "rsi": self._calculate_rsi([float(k[4]) for k in klines]),
                    "regime": regime.get("regime", "Unknown") if regime else "Unknown",
                    "regime_conf": regime.get("conf", 0.0) if regime else 0.0
                }
                
                prompt = PromptBuilder.build_narrative(symbol, market_data)
                
                # 3. Query LLM (Slow Step)
                response = await self._query_llm(prompt)
                
                # 4. Process Decision
                if response:
                    # Parse sanitized
                    decision = self._parse_llm_response(response)
                    if not decision:
                        self._queue.task_done()
                        continue

                    # Update Telemetry
                    self.last_confidence = decision["confidence"]
                    self.last_reasoning = decision["reasoning"]
                    sentiment_score = decision.get("sentiment_score", 0.0)
                    
                    # Fire Event (Async processing complete)
                    payload = {
                        "symbol": symbol,
                        "action": decision["side"], # BUY/SELL/HOLD
                        "confidence": self.last_confidence,
                        "sentiment_score": sentiment_score,
                        "reasoning": self.last_reasoning,
                        "price": price,
                        "ts": time.time()
                    }
                    
                    # Publish to Event Bus for Execution
                    BUS.fire("strategy.deepseek_signal", payload)
                    logger.info(f"🧠 DeepSeek Decision: {payload['action']} {symbol} (Conf: {payload['confidence']:.2f}, Sent: {sentiment_score:.2f})")

                self._queue.task_done()
                
            except Exception as e:
                logger.error(f"DeepSeek Worker Warning: {e}", exc_info=True)
                await asyncio.sleep(1.0) # Backoff on error


    async def _fetch_klines(self, symbol: str, interval: str, limit: int) -> list:
        # Simple public API fetch implementation
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Failed to fetch klines for {symbol}: {e}")
            return []

    def _build_prompt(self, symbol: str, klines: list, regime: dict) -> str:
        # Simplified features
        opens = [float(k[1]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        current_price = closes[-1]
        
        rsi = self._calculate_rsi(closes)
        
        regime_str = "Unknown"
        if regime:
            regime_str = f"{regime.get('regime', 'Unknown')} (Conf: {regime.get('conf', 0):.2f})"

        prompt = f"""
        You are an expert crypto trading bot.
        Analyze the following market data for {symbol}:
        
        - Current Price: {current_price}
        - 14-period RSI: {rsi:.2f}
        - Market Regime (HMM): {regime_str}
        - Last 5 Closes: {closes[-5:]}
        
        Your task: Decision (BUY, SELL, HOLD).
        Criteria:
        - Trend Alignment: Are we in a BULL or BEAR regime?
        - Momentum: Is RSI overbought (>70) or oversold (<30)?
        
        Return STRICT JSON format only:
        {{ "action": "BUY/SELL/HOLD", "sentiment_score": -1.0 to 1.0, "confidence": 0.0-1.0, "reasoning": "short explanation" }}
        """
        return prompt

    def _calculate_rsi(self, prices: list, period=14) -> float:
        if len(prices) < period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            gains.append(max(delta, 0))
            losses.append(abs(min(delta, 0)))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    async def _query_llm(self, prompt: str) -> dict | None:
        """
        Queries the LLM backend. 
        Auto-detects format based on URL (Ollama vs OpenAI/DeepSeek Cloud).
        """
        try:
            if self.is_local:
                # Ollama Format
                payload = {
                    "model": self.cfg.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
                resp = await self._client.post(self.cfg.api_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return json.loads(data["response"])
            else:
                # OpenAI / DeepSeek Cloud Format
                headers = {
                    "Authorization": f"Bearer {self.cfg.api_key}",
                    "Content-Type": "application/json"
                }
                # Handles DeepSeek specific endpoint structure if needed, but usually /chat/completions
                endpoint = f"{self.cfg.api_url}/chat/completions" if not self.cfg.api_url.endswith("/chat/completions") else self.cfg.api_url
                
                payload = {
                    "model": self.cfg.model,
                    "messages": [
                        {"role": "system", "content": "You are a JSON-only trading assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"}
                }
                
                resp = await self._client.post(endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
                
        except Exception as e:
            logger.warning(f"LLM Query Failed: {e}")
            return None

    def _parse_llm_response(self, response: dict) -> dict | None:
        action = response.get("action", "HOLD").upper()
        if action not in ["BUY", "SELL", "HOLD"]:
            return None
        return {
            "side": action,
            "confidence": float(response.get("confidence", 0)),
            "sentiment_score": float(response.get("sentiment_score", 0.0)),
            "reasoning": response.get("reasoning", "")
        }

    def _create_order(self, symbol: str, price: float, decision: dict) -> dict:
        quote = 100.0 # Placeholder
        return {
            "symbol": symbol,
            "side": decision["side"],
            "quote": quote,
            "tag": "deepseek_v2",
            "meta": {
                "confidence": decision["confidence"],
                "reasoning": decision["reasoning"]
            },
            "market": "futures"
        }
