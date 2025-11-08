#!/usr/bin/env python3
import json
import os
import statistics
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DATA_PATH = "data/collective"
os.makedirs(DATA_PATH, exist_ok=True)

APP = FastAPI(title="Collective Hub")
SUBMISSIONS = os.path.join(DATA_PATH, "submissions.jsonl")
AGGREGATE = os.path.join(DATA_PATH, "aggregate.json")


@APP.post("/submit")
async def submit(req: Request):
    data = await req.json()
    data["time"] = datetime.utcnow().isoformat()
    with open(SUBMISSIONS, "a", encoding="utf-8") as f:
        f.write(json.dumps(data) + "\n")
    return {"status": "accepted"}


@APP.get("/aggregate")
def aggregate():
    if not os.path.exists(SUBMISSIONS):
        return JSONResponse({"status": "empty"})
    with open(SUBMISSIONS, encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh]
    if not records:
        return {"status": "no_data"}
    # Compute consensus stats
    metrics = ["avg_reward", "winrate", "entropy", "drift_score"]
    agg = {m: statistics.mean([r.get(m, 0) for r in records if m in r]) for m in metrics}
    agg["n_nodes"] = len(records)
    agg["updated"] = datetime.utcnow().isoformat()
    with open(AGGREGATE, "w", encoding="utf-8") as fh:
        json.dump(agg, fh, indent=2)
    return agg


@APP.get("/status")
def status():
    if not os.path.exists(AGGREGATE):
        return JSONResponse({"status": "no_aggregate"})
    with open(AGGREGATE, encoding="utf-8") as fh:
        payload = json.load(fh)
    return JSONResponse(payload)
