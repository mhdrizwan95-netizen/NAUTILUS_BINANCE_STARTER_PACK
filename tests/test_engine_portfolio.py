import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from engine.core.portfolio import Portfolio


def test_portfolio_apply_fill_buy_sell_cycle():
    portfolio = Portfolio(starting_cash=10000.0)

    # Simulate buy 0.001 BTC at 30000
    portfolio.apply_fill("BTCUSDT.BINANCE", "BUY", 0.001, 30000.0, fee_usd=0.03)
    state = portfolio.state
    assert state.cash == 10000.0 - (0.001 * 30000.0 + 0.03)
    assert state.positions["BTCUSDT.BINANCE"].quantity == 0.001

    # Update mark price
    portfolio.update_price("BTCUSDT.BINANCE", 31000.0)
    state = portfolio.state
    assert round(state.unrealized, 2) == round(0.001 * (31000 - 30000), 2)

    # Sell position
    portfolio.apply_fill("BTCUSDT.BINANCE", "SELL", 0.001, 31000.0, fee_usd=0.031)
    state = portfolio.state
    assert state.positions == {}
    assert state.exposure == 0.0
    assert state.unrealized == 0.0
    # realized pnl minus fees
    assert state.realized > 0
