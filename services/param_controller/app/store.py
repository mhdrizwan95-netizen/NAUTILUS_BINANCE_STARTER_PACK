
import os, sqlite3, json, time
from pathlib import Path
from typing import Dict, Any, List, Tuple

DDL = """
CREATE TABLE IF NOT EXISTS presets(
  strategy TEXT,
  instrument TEXT,
  preset_id TEXT,
  params_json TEXT,
  PRIMARY KEY(strategy, instrument, preset_id)
);
CREATE TABLE IF NOT EXISTS outcomes(
  ts REAL, strategy TEXT, instrument TEXT, preset_id TEXT, reward REAL, features_json TEXT
);
"""

def connect(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path, timeout=30, check_same_thread=False)

def init(db_path: str):
    conn = connect(db_path); cur = conn.cursor()
    for stmt in DDL.strip().split(";"):
        s = stmt.strip()
        if s: cur.execute(s)
    conn.commit(); conn.close()

def upsert_preset(db_path: str, strategy: str, instrument: str, preset_id: str, params: dict):
    conn = connect(db_path); cur = conn.cursor()
    cur.execute("""INSERT INTO presets(strategy,instrument,preset_id,params_json)
                   VALUES(?,?,?,?)
                   ON CONFLICT(strategy,instrument,preset_id) DO UPDATE SET params_json=excluded.params_json""",
                (strategy, instrument, preset_id, json.dumps(params)))
    conn.commit(); conn.close()

def list_presets(db_path: str, strategy: str, instrument: str) -> List[Tuple[str, dict]]:
    conn = connect(db_path); cur = conn.cursor()
    cur.execute("SELECT preset_id, params_json FROM presets WHERE strategy=? AND instrument=? ORDER BY preset_id ASC",
                (strategy, instrument))
    rows = [(r[0], json.loads(r[1])) for r in cur.fetchall()]
    conn.close()
    return rows

def log_outcome(db_path: str, strategy: str, instrument: str, preset_id: str, reward: float, features: dict):
    conn = connect(db_path); cur = conn.cursor()
    cur.execute("INSERT INTO outcomes(ts,strategy,instrument,preset_id,reward,features_json) VALUES(?,?,?,?,?,?)",
                (time.time(), strategy, instrument, preset_id, float(reward), json.dumps(features)))
    conn.commit(); conn.close()
