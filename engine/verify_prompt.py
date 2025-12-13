
import sys
import os

sys.path.append(os.getcwd())

from engine.strategies.prompt_builder import PromptBuilder

data = {
    "price": 100000.0,
    "rsi": 75.0,
    "regime": "Bullish",
    "regime_conf": 0.85,
    "recent_closes": [98000, 99000, 99500, 99800, 100000] # Up trend
}

try:
    prompt = PromptBuilder.build_narrative("BTCUSDT", data)
    print("✅ Prompt Builder Success")
    print("-" * 20)
    print(prompt)
    print("-" * 20)
    
    if "RSI (14): 75.00 (Overbought)" not in prompt:
        raise ValueError("RSI logic failed")
    if "Short-Term Trend (5 bars): Up" not in prompt:
        raise ValueError("Trend logic failed")
        
except Exception as e:
    print(f"❌ Prompt Builder Failed: {e}")
    import traceback
    traceback.print_exc()
