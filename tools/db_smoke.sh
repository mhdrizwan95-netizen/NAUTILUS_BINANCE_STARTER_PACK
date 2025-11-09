#!/usr/bin/env bash
set -euo pipefail

echo "[DB Smoke] Engine SQLite init + insert"
python - <<'PY'
from engine.storage import sqlite as store
from pathlib import Path
db = 'data/runtime/test_trades.db'
Path('data/runtime').mkdir(parents=True, exist_ok=True)
store.init(db_path=db)
store.insert_order({
  'id':'o1','venue':'binance','symbol':'BTCUSDT','side':'BUY','qty':0.001,'price':50000.0,
  'status':'PLACED','ts_accept':1234567890,'ts_update':1234567890
})
store.insert_fill({
  'id':'f1','order_id':'o1','venue':'binance','symbol':'BTCUSDT','side':'BUY','qty':0.001,
  'price':50000.0,'fee_ccy':'USDT','fee':0.05,'ts':1234567891
})
print('OK: enqueued records; waiting flush...')
import time; time.sleep(1.0)
PY
sqlite3 data/runtime/test_trades.db '.tables' | grep -q orders && echo "OK: orders table present" || (echo "ERR: orders table missing"; exit 1)

echo "[DB Smoke] Manifest ledger init + register/claim"
python - <<'PY'
from services.common import manifest
from pathlib import Path
import os, time
db='data/runtime/test_manifest.sqlite'
manifest.init(db)
p=Path('data/incoming/BTC_USDT/1m'); p.mkdir(parents=True, exist_ok=True)
f=p/'test.csv'
f.write_text('timestamp,close\n0,1\n1,2\n')
fid, inserted = manifest.register_file(str(f), 'BTC/USDT', '1m', 0, 1, db)
rows = manifest.claim_unprocessed(limit=1, db_path=db)
assert rows and rows[0]['file_id']==fid
manifest.mark_processed(fid, delete_file=True, db_path=db)
print('OK: ledger claim/process passed')
PY
echo "DB smoke finished"
