# M4: strategy.py (Nautilus Strategy subclass)
import asyncio
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.events import OrderBookDelta
from nautilus_trader.model.enums import OrderSide, PositionSide
from nautilus_trader.model.orders import LimitOrder
from nautilus_trader.strategies import TradingStrategy
from nautilus_trader.core import UUID4
from .config import HMMPolicyConfig
from .features import FeatureState, compute_features
from .policy import decide_action
from .guardrails import check_gates, Block, compute_vwap_anchored_fair_price
from .telemetry import Telemetry
from .telemetry_ops import publish_metrics_throttled

class HMMPolicyStrategy(TradingStrategy):
    def __init__(self, config: HMMPolicyConfig):
        # Convert HMMPolicyConfig to StrategyConfig
        strategy_config = StrategyConfig(order_id_tag="HMM")
        super().__init__(strategy_config)
        self.cfg = config
        self.instrument = self.model_instrument(config.instrument)
        self.state = FeatureState()
        self.telemetry = Telemetry()
        self._last_action_ns = 0

        # Subscribe to required data in on_start
        self.register_instrument(self.instrument)

    def on_start(self):
        # Subscribe to order book deltas and trade ticks (for trades in features)
        self.subscribe_order_book_deltas(self.instrument.id)
        self.subscribe_trade_ticks(self.instrument.id)

    def on_order_book_delta(self, event: OrderBookDelta):
        if event.instrument_id != self.instrument.id:
            return

        # Fetch recent trades from cache (last few ticks)
        recent_trades = self.cache.trade_ticks(self.instrument.id)  # list or dict

        # Compute features
        feats = compute_features(None, event.order_book_immutable, recent_trades.values() if hasattr(recent_trades, 'values') else recent_trades, self.state)

        # macro features
        from .features import MacroMicroFeatures
        if not hasattr(self, 'mm'):
            self.mm = MacroMicroFeatures()
        mid = (event.order_book_immutable.best_bid_price + event.order_book_immutable.best_ask_price) / 2.0
        spread_bp = (event.order_book_immutable.best_ask_price - event.order_book_immutable.best_bid_price) / mid * 10000.0
        self.mm.update(mid, spread_bp)
        macro_vec = self.mm.macro_feats().tolist()
        micro_vec = feats.tolist()

        # Check if H2 is enabled
        use_h2 = getattr(self.cfg, 'use_h2', False)

        # Call ML service
        try:
            import httpx
            timeout=0.25
            if use_h2:
                resp = httpx.post(f"{self.cfg.hmm_url}/infer_h2", json={
                    "symbol": self.cfg.instrument.split(".")[0],
                    "macro_feats": macro_vec,
                    "micro_feats": micro_vec,
                    "ts": event.ts_ns,
                }, timeout=timeout)
                resp.raise_for_status()
                result = resp.json()
                macro_state = result["macro_state"]
                micro_state = result["micro_state"]
                conf = result["confidence"]
            else:
                resp = httpx.post(f"{self.cfg.hmm_url}/infer", json={
                    "symbol": self.cfg.instrument,
                    "features": feats.tolist(),
                    "ts": event.ts_ns
                }, timeout=timeout)
                resp.raise_for_status()
                result = resp.json()
                macro_state = 1; micro_state = result["state"]; conf = result["confidence"]

            action = result["action"]
            side = action["side"]
            qty = action["qty"]
            # macro-aware guardrails: shrink risk in risk-off
            risk_bias = {0:0.5, 1:1.0, 2:1.5}.get(macro_state, 1.0)
            qty *= risk_bias
            limit_px = action.get("limit_px") or event.order_book_immutable.best_bid_price  # fallback
        except Exception as e:
            self.log.info(f"ML error: {e}, going HOLD")
            self.telemetry.count("ml_error", labels={"error": str(e)})
            macro_state, micro_state, conf = 1, 0, 1.0
            side, qty, limit_px = "HOLD", 0, None

        # LIVE-2: Publish metrics to Ops API (non-blocking)
        try:
            # Calculate basic metrics we can derive
            pnl_metrics = {
                "pnl_realized": getattr(self.portfolio, "unrealized_pnl", {}).get(self.instrument.id, 0.0) if hasattr(self, 'portfolio') else 0.0,
                "pnl_unrealized": getattr(self.portfolio, "unrealized_pnl", {}).get(self.instrument.id, 0.0) if hasattr(self, 'portfolio') else 0.0,
                "drift_score": macro_state * 0.1 if macro_state != 1 else 0.0,  # rough drift proxy
                "policy_confidence": conf,
                "order_fill_ratio": 0.8,  # TODO: implement fill ratio tracking
                "venue_latency_ms": spread_bp * 10,  # rough latency proxy
            }
            publish_metrics_throttled(pnl_metrics, min_interval_sec=2.0)
        except Exception as e:
            # telemetry should never break trading
            pass

        # Apply guardrails
        if side == "HOLD":
            return

        # Create context for guardrails
        ctx = type("Ctx", (), {
            "cfg": self.cfg,
            "state": self.state,
            "book": event.order_book_immutable,
            "instrument_id": self.instrument.id.string,
            "trading_enabled": True,
            "_last_action_ns": self._last_action_ns,
            "vwap": getattr(self, "running_vwap", 0.0),
            "cum_vol": getattr(self, "cum_vol", 0.0)
        })()

        # Compute spread_bp
        bid_px = event.order_book_immutable.best_bid_price
        ask_px = event.order_book_immutable.best_ask_price
        spread_bp = ((ask_px - bid_px) / ((bid_px + ask_px) / 2)) * 10000.0 if ask_px > bid_px else 0.0

        # Compute VWAP update from trades
        ctx.vwap = compute_vwap_anchored_fair_price(ctx, event.order_book_immutable, recent_trades)

        block = check_gates(ctx, event.ts_ns, spread_bp, abs(qty), self.portfolio, self.telemetry)
        if block is not Block.OK:
            return

        # Submit order
        order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL
        quantity = self.instrument.make_qty(abs(qty))
        order = LimitOrder(
            trader_id=self.trader_id,
            strategy_id=self.id,
            instrument_id=self.instrument.id,
            order_side=order_side,
            quantity=quantity,
            price=self.instrument.make_price(limit_px),
            order_id=UUID4(),
            init_id=UUID4(),
            ts_init=self.clock_ns(),
        )
        self.submit_order(order)
        self.telemetry.count("orders_submitted", labels={"side": side})
        self._last_action_ns = event.ts_ns  # update for cooldown
        self.running_vwap = ctx.vwap  # persist VWAP
        self.cum_vol = ctx.cum_vol
