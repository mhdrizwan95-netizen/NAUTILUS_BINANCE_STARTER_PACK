#!/usr/bin/env python3
import os, hmac, hashlib, time, urllib.parse, httpx
from typing import Dict, Any


def _now_ms() -> int:
    return int(time.time() * 1000)


class BinanceAccountProvider:
    """
    Unified provider for Spot + Futures (USD-M + COIN-M).
    Works for both:
      - BINANCE_MODE=live  -> api.binance.com, fapi.binance.com, dapi.binance.com
      - BINANCE_MODE=demo  -> testnet bases from .env
    """

    def __init__(self):
        mode = os.getenv("BINANCE_MODE", "live").lower()

        if mode == "demo":
            self.spot_base = os.getenv(
                "DEMO_SPOT_BASE", "https://testnet.binance.vision"
            )
            self.usdm_base = os.getenv(
                "DEMO_USDM_BASE", "https://testnet.binancefuture.com"
            )
            self.coinm_base = os.getenv(
                "DEMO_COINM_BASE", "https://testnet.binancefuture.com"
            )
            key_candidates = [
                os.getenv("DEMO_API_KEY_SPOT"),
                os.getenv("DEMO_API_KEY_USDM"),
                os.getenv("DEMO_API_KEY"),
                os.getenv("BINANCE_API_KEY", ""),
            ]
            secret_candidates = [
                os.getenv("DEMO_API_SECRET_SPOT"),
                os.getenv("DEMO_API_SECRET_USDM"),
                os.getenv("DEMO_API_SECRET"),
                os.getenv("BINANCE_API_SECRET", ""),
            ]
        else:
            self.spot_base = os.getenv("BINANCE_SPOT_BASE", "https://api.binance.com")
            self.usdm_base = os.getenv("BINANCE_USDM_BASE", "https://fapi.binance.com")
            self.coinm_base = os.getenv(
                "BINANCE_COINM_BASE", "https://dapi.binance.com"
            )
            key_candidates = [os.getenv("BINANCE_API_KEY", "")]
            secret_candidates = [os.getenv("BINANCE_API_SECRET", "")]

        self.api_key = next((v for v in key_candidates if v), "")
        self.api_secret = next((v for v in secret_candidates if v), "")

        self.recv_window = int(os.getenv("BINANCE_RECV_WINDOW", "5000"))
        self.timeout = int(os.getenv("BINANCE_API_TIMEOUT", "10"))

        self.headers = {"X-MBX-APIKEY": self.api_key}
        self.http = httpx.AsyncClient(timeout=self.timeout)

    def _sign(self, params: Dict[str, Any]) -> str:
        query = urllib.parse.urlencode(params, doseq=True)
        return hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()

    async def _get(
        self,
        base: str,
        path: str,
        auth: bool = True,
        params: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        params = dict(params or {})
        if auth:
            params["timestamp"] = _now_ms()
            params["recvWindow"] = self.recv_window
            params["signature"] = self._sign(params)
        url = f"{base}{path}"
        r = await self.http.get(url, params=params, headers=self.headers)
        r.raise_for_status()
        return r.json()

    async def fetch_spot_account(self) -> Dict[str, Any]:
        # GET /api/v3/account
        return await self._get(self.spot_base, "/api/v3/account", auth=True)

    async def fetch_usdm_account(self) -> Dict[str, Any]:
        # GET /fapi/v2/account
        return await self._get(self.usdm_base, "/fapi/v2/account", auth=True)

    async def fetch_coinm_account(self) -> Dict[str, Any]:
        # GET /dapi/v1/account
        return await self._get(self.coinm_base, "/dapi/v1/account", auth=True)

    async def fetch(self) -> Dict[str, Any]:
        """
        Returns a compact metrics dict used by ops snapshot code.
        We try all three markets; if one fails, we continue.
        """
        spot, usdm, coinm = {}, {}, {}
        try:
            spot = await self.fetch_spot_account()
        except Exception:
            pass
        try:
            usdm = await self.fetch_usdm_account()
        except Exception:
            pass
        try:
            coinm = await self.fetch_coinm_account()
        except Exception:
            pass

        # Simplified equity estimates:
        # Spot: sum of free + locked *assumed in USDT terms if asset == USDT (otherwise 0 for compactness)
        def spot_equity_usdt(sp: Dict[str, Any]) -> float:
            bal = 0.0
            for a in sp.get("balances", []):
                if a.get("asset") == "USDT":
                    bal += float(a.get("free", 0)) + float(a.get("locked", 0))
            return bal

        # Futures balances often provide "totalWalletBalance" in USDT (USD-M)
        def usdm_equity_usdt(fut: Dict[str, Any]) -> float:
            try:
                return float(fut.get("totalWalletBalance", 0))
            except Exception:
                return 0.0

        # COIN-M: sum wallet balances across assets (approx in their asset terms; left as 0 for simplicity)
        def coinm_equity_est(cm: Dict[str, Any]) -> float:
            try:
                return sum(
                    float(x.get("walletBalance", 0)) for x in cm.get("assets", [])
                )
            except Exception:
                return 0.0

        metrics = {
            "spot_equity_usdt": spot_equity_usdt(spot) if spot else 0.0,
            "usdm_equity_usdt": usdm_equity_usdt(usdm) if usdm else 0.0,
            "coinm_equity_est": coinm_equity_est(coinm) if coinm else 0.0,
            # placeholders to keep dashboard happy
            "pnl_realized": 0.0,
            "pnl_unrealized": 0.0,
            "order_fill_ratio": 0.0,
            "policy_confidence": 0.0,
            "drift_score": 0.0,
            "venue_latency_ms": 0.0,
        }
        return metrics

    def snapshot(self):
        """Synchronous wrapper for backward compatibility"""
        import asyncio

        async def _get_snapshot():
            return await self.fetch()

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_get_snapshot())
        finally:
            loop.close()
