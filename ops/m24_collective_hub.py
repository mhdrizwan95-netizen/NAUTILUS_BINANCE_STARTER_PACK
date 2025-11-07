#!/usr/bin/env python3
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from datetime import datetime
import os, json, statistics

DATA_PATH = "data/collective"
os.makedirs(DATA_PATH, exist_ok=True)

APP = FastAPI(title="Collective Hub")
SUBMISSIONS = os.path.join(DATA_PATH, "submissions.jsonl")
AGGREGATE = os.path.join(DATA_PATH, "aggregate.json")


@APP.post("/submit")
async def submit(req: Request):
    data = await req.json()
    data["time"] = datetime.utcnow().isoformat()
    with open(SUBMISSIONS, "a") as f:
        f.write(json.dumps(data) + "\n")
    return {"status": "accepted"}


@APP.get("/aggregate")
def aggregate():
    if not os.path.exists(SUBMISSIONS):
        return JSONResponse({"status": "empty"})
    records = [json.loads(l) for l in open(SUBMISSIONS)]
    if not records:
        return {"status": "no_data"}
    # Compute consensus stats
    metrics = ["avg_reward", "winrate", "entropy", "drift_score"]
    agg = {m: statistics.mean([r.get(m, 0) for r in records if m in r]) for m in metrics}
    agg["n_nodes"] = len(records)
    agg["updated"] = datetime.utcnow().isoformat()
    json.dump(agg, open(AGGREGATE, "w"), indent=2)
    return agg


@APP.get("/status")
def status():
    return JSONResponse(
        json.load(open(AGGREGATE)) if os.path.exists(AGGREGATE) else {"status": "no_aggregate"}
    )
