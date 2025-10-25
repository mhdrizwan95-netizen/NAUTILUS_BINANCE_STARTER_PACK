import json, time
def replay_ticks(path: str, on_tick):
    with open(path) as f:
        for line in f:
            t = json.loads(line)  # {"ts":..., "symbol":"PI_XBTUSD", "price":...}
            on_tick(t["symbol"], t["price"], t["ts"])
            time.sleep(0.01)  # fast-forward; tune as needed
