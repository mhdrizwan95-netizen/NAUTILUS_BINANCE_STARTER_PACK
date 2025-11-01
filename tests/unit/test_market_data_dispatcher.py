import asyncio
import logging

from engine.feeds.market_data_dispatcher import MarketDataDispatcher, MarketDataLogger
from engine import metrics


class DummyBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def fire(self, topic: str, data: dict) -> None:
        self.events.append((topic, data))

    def subscribe(self, topic: str, handler):
        self.events.append(("subscribe", (topic, handler)))

    def unsubscribe(self, topic: str, handler):
        self.events.append(("unsubscribe", (topic, handler)))


def test_dispatcher_routes_events_and_enriches_payload() -> None:
    bus = DummyBus()
    dispatcher = MarketDataDispatcher(bus, source="unit", venue="BINANCE")
    counter = metrics.market_data_events_total.labels(source="unit", type="tick")
    before = counter._value.get()
    dispatcher.handle_stream_event(
        {"type": "tick", "symbol": "BTCUSDT.BINANCE", "price": 123.45, "ts": 1.0}
    )
    assert bus.events, "dispatcher should publish to bus"
    topic, data = bus.events[-1]
    assert topic == "market.tick"
    assert data["source"] == "unit"
    assert data["venue"] == "BINANCE"
    assert data["symbol"] == "BTCUSDT.BINANCE"
    after = counter._value.get()
    assert after == before + 1


def test_dispatcher_classifies_trade_events() -> None:
    bus = DummyBus()
    dispatcher = MarketDataDispatcher(bus, source="unit", venue="BINANCE")
    dispatcher.handle_stream_event(
        {
            "type": "trade",
            "symbol": "ETHUSDT.BINANCE",
            "price": 10.0,
            "ts": 2.0,
            "quantity": 0.1,
        }
    )
    topic, data = bus.events[-1]
    assert topic == "market.trade"
    assert data["symbol"] == "ETHUSDT.BINANCE"
    assert data["source"] == "unit"


def test_market_data_logger_subscribes_and_logs(caplog) -> None:
    class LoggerBus:
        def __init__(self) -> None:
            self.handlers: dict[str, list] = {}

        def fire(self, topic: str, data: dict) -> None:
            raise NotImplementedError

        def subscribe(self, topic: str, handler) -> None:
            self.handlers.setdefault(topic, []).append(handler)

        def unsubscribe(self, topic: str, handler) -> None:
            if topic in self.handlers:
                self.handlers[topic].remove(handler)

    bus = LoggerBus()
    mdl = MarketDataLogger(
        bus, sample_rate_hz=1000.0, logger=logging.getLogger("test-md")
    )
    mdl.start()
    assert "market.tick" in bus.handlers
    handler = bus.handlers["market.tick"][0]
    with caplog.at_level(logging.INFO):
        asyncio.run(handler({"symbol": "BTCUSDT.BINANCE", "price": 99.0, "ts": 5.0}))
    assert any("[MD]" in rec.message for rec in caplog.records)
    mdl.stop()
    assert "market.tick" not in bus.handlers or not bus.handlers["market.tick"]
