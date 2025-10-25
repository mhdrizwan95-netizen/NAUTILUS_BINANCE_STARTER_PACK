from engine.metrics import event_bo_plans_total, event_bo_skips_total


def test_metrics_label_cardinality():
    assert tuple(event_bo_plans_total._labelnames) == ("venue", "symbol", "dry")
    assert tuple(event_bo_skips_total._labelnames) == ("reason", "symbol")

