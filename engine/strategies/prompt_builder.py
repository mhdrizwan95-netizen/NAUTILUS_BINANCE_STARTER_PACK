
from __future__ import annotations
import math

class PromptBuilder:
    """
    Translates technical indicators into a narrative for the LLM.
    Reduces hallucination by formatting inputs rigidly.
    """
    
    @staticmethod
    def build_narrative(symbol: str, market_data: dict) -> str:
        """
        Constructs a structured narrative from market data.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            market_data: dict containing:
                - price: float
                - rsi: float
                - regime: str
                - regime_conf: float
                - recent_closes: list[float]
                
        Returns:
            Formatted prompt string.
        """
        price = market_data.get("price", 0.0)
        rsi = market_data.get("rsi", 50.0)
        regime = market_data.get("regime", "Unknown")
        regime_conf = market_data.get("regime_conf", 0.0)
        closes = market_data.get("recent_closes", [])
        
        # Derived Analysis
        rsi_state = "Neutral"
        if rsi > 70:
            rsi_state = "Overbought"
        elif rsi < 30:
            rsi_state = "Oversold"
            
        trend_short = "Flat"
        if len(closes) >= 5:
            start = closes[0]
            end = closes[-1]
            if end > start * 1.01:
                trend_short = "Up"
            elif end < start * 0.99:
                trend_short = "Down"

        prompt = f"""
        You are an expert crypto trading bot.
        
        MARKET STATUS REPORT: {symbol}
        --------------------------------
        Current Price: {price}
        
        TECHNICALS:
        - RSI (14): {rsi:.2f} ({rsi_state})
        - Short-Term Trend (5 bars): {trend_short}
        
        QUANTITATIVE ANALYSIS (HMM):
        - Market Regime: {regime}
        - Regime Confidence: {regime_conf:.2f}
        
        TASK:
        Based strictly on the data above, determine the optimal trade action.
        
        INSTRUCTIONS:
        1. If RSI is Extreme (>70 or <30) AND Regime supports reversal -> High Probability Reversal.
        2. If RSI is Neutral AND Regime is Trending -> Trend Continuation.
        3. Provide a recommended position size (Quote Amount in USDT).
        
        OUTPUT FORMAT (JSON ONLY):
        {{
            "action": "BUY" | "SELL" | "HOLD",
            "confidence": 0.0 to 1.0,
            "quote": <amount_usdt_recommendation>,
            "reasoning": "<concise_explanation>"
        }}
        """
        return prompt
