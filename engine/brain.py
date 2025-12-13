import logging
import time
from typing import Dict, Optional, Tuple
from collections import defaultdict

from engine.strategies import policy_hmm

logger = logging.getLogger(__name__)

class NautilusBrain:
    """
    The 'Conductor' of the ensemble.
    Aggregates signals from:
    1. HMM (Regime Detection) -> Sets the 'Stage' (Bull/Bear/Chop).
    2. DeepSeek (Sentiment Analysis) -> Acts as a 'Veto' or 'Booster'.
    3. Stat Arb (Mean Reversion) -> Active mainly in 'Chop' regime.
    """
    def __init__(self):
        # Configuration
        self.sentiment_threshold = 0.5 # Absolute value required to act
        self.news_veto_level = -0.5    # If sentiment < -0.5, block LONGS
        
        # State
        self._latest_sentiment: Dict[str, float] = defaultdict(float)
        self._latest_sentiment_ts: Dict[str, float] = defaultdict(float)
        self.sentiment_expiry = 600 # Sentiment counts for 10 mins
        
    def update_sentiment(self, symbol: str, score: float, ts: float):
        """Called when a new async DeepSeek signal arrives."""
        self._latest_sentiment[symbol] = score
        self._latest_sentiment_ts[symbol] = ts
        
    def get_decision(self, symbol: str, price: float) -> Tuple[Optional[str], float, Dict]:
        """
        Main decision loop.
        Returns (Side, SizeFactor, Meta) or (None, 0.0, {}).
        """
        # 1. Get Market Regime (The Stage)
        # HMM is synchronous/cached
        regime_data = policy_hmm.get_regime(symbol.split(".")[0])
        if not regime_data:
            return None, 0.0, {}
            
        regime = regime_data.get("regime", "CHOP")
        conf = regime_data.get("conf", 0.0)
        
        # 2. Get Sentiment (The Veto/Boost)
        sentiment = self._get_valid_sentiment(symbol)
        
        # 3. Logic Ensemble
        # Default policy: Follow Regime, but Veto if Sentiment contradicts strongly
        
        side = None
        size_factor = 1.0
        reason = []
        
        # --- Regime Logic ---
        if regime == "BULL":
            if sentiment < self.news_veto_level:
                reason.append(f"VETO: Bull regime but Sentiment {sentiment:.2f} < {self.news_veto_level}")
                side = None # Block
            else:
                side = "BUY"
                reason.append("Bull Regime Follow")
                if sentiment > 0.5:
                    size_factor = 1.2 # Boost
                    reason.append(f"Sentiment Boost {sentiment:.2f}")
                    
        elif regime == "BEAR":
            if sentiment > 0.5: # Hard to go short if everyone is super bullish? Maybe.
                # For safety, maybe reduce size
                size_factor = 0.5
                reason.append(f"Dampener: Bear regime but Sentiment {sentiment:.2f} > 0.5")
            side = "SELL"
            
        elif regime == "CHOP":
            # In Chop, we usually wait for Mean Reversion (Phase 3 Stat Arb)
            # For now, if we don't have Stat Arb wired here yet, we look for extreme sentiment?
            # Or we simply HOLD.
            if abs(sentiment) > 0.8:
                # Contrarian or Breakout? 
                # Let's assume high sentiment in Chop means Breakout imminent
                side = "BUY" if sentiment > 0 else "SELL"
                reason.append(f"Chop Breakout: Extreme Sentiment {sentiment:.2f}")
            else:
                side = None
                reason.append("Chop Regime: Waiting for MeanRev or Breakout")

        if not side:
            return None, 0.0, {"brain_reason": "; ".join(reason)}
            
        meta = {
            "regime": regime,
            "regime_conf": conf,
            "sentiment": sentiment,
            "brain_reason": "; ".join(reason)
        }
        
        return side, size_factor, meta

    def _get_valid_sentiment(self, symbol: str) -> float:
        ts = self._latest_sentiment_ts.get(symbol, 0)
        if time.time() - ts > self.sentiment_expiry:
            return 0.0 # Expired/Neutral
        return self._latest_sentiment.get(symbol, 0.0)
