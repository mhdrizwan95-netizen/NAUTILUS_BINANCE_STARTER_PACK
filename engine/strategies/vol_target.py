import math
import logging
from collections import deque

logger = logging.getLogger(__name__)

class VolatilityManager:
    """
    Manages volatility estimation and position sizing based on Institutional Volatility Targeting.
    Uses Exponential Moving Average (EMA) of squared log-returns.
    """
    def __init__(self, target_vol_ann: float = 0.40, window: int = 20, decay: float = 0.94):
        """
        :param target_vol_ann: Target Annualized Volatility (e.g., 0.40 = 40%)
        :param window: Looking back window for simple vol (seeding)
        :param decay: Decay factor for EMA variance (typically 0.94 for RiskMetrics)
        """
        self.target_vol = target_vol_ann
        self.decay = decay
        self.window = window
        
        self.prices = deque(maxlen=window + 1)
        self.returns = deque(maxlen=window)
        
        self.current_variance = 0.0
        self.last_price = 0.0
        
        # Crypto runs 24/7. Minutes per year approx: 365 * 24 * 60 = 525600
        self.ann_factor = 525600.0 

    def update(self, price: float):
        if price <= 0:
            return

        self.prices.append(price)
        
        if self.last_price > 0:
            # Log return
            try:
                ret = math.log(price / self.last_price)
            except ValueError:
                ret = 0.0
            
            self.returns.append(ret)
            ret_sq = ret * ret
            
            # Update EMA Variance
            # If seeding (less than window), use simple variance
            if len(self.returns) < self.window:
                # Accumulate simple variance
                self.current_variance = sum(r*r for r in self.returns) / len(self.returns)
            else:
                # EMWA: Var_t = lambda * Var_t-1 + (1-lambda) * r_t^2
                self.current_variance = (self.decay * self.current_variance) + ((1.0 - self.decay) * ret_sq)
        
        self.last_price = price

    def get_annualized_vol(self) -> float:
        """Returns annualized volatility (sigma)."""
        if self.current_variance <= 0:
            return 0.0
        
        # Daily/Minute vol
        period_vol = math.sqrt(self.current_variance)
        return period_vol * math.sqrt(self.ann_factor)

    def get_target_exposure(self, equity: float, cap_leverage: float = 2.0) -> float:
        """
        Calculates target position size (in USDT) to hit target volatility.
        Formula: Exposure = (TargetVol / RealizedVol) * Equity
        """
        vol = self.get_annualized_vol()
        if vol <= 0.001: 
             # Fallback if vol is near zero (e.g. flat line), likely extremely safe or data error.
             # Cap at nominal leverage to be safe.
             return equity * 1.0

        # Raw target
        # e.g. Target 40%, Realized 80% -> 0.5 leverage
        # e.g. Target 40%, Realized 10% -> 4.0 leverage (dangerous, hence cap)
        leverage_factor = self.target_vol / vol
        
        # Cap leverage
        if leverage_factor > cap_leverage:
            leverage_factor = cap_leverage
            
        return equity * leverage_factor

    def apply_half_kelly(self, prob_win: float, payoff_ratio: float, exposure: float) -> float:
        """
        Scales exposure down if Kelly Criterion suggests lower size.
        Half-Kelly = 0.5 * (p - q/b)
        """
        if payoff_ratio <= 0:
            return 0.0
            
        q = 1.0 - prob_win
        kelly_fraction = prob_win - (q / payoff_ratio)
        
        half_kelly = 0.5 * kelly_fraction
        
        if half_kelly <= 0:
            return 0.0
            
        return exposure
