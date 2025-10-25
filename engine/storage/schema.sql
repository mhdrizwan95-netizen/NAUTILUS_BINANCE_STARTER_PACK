PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS orders (
  id            TEXT PRIMARY KEY,             -- engine/order id
  venue         TEXT NOT NULL,
  symbol        TEXT NOT NULL,
  side          TEXT NOT NULL,                -- BUY/SELL
  qty           REAL NOT NULL,
  price         REAL,                          -- null for pure market at accept time
  status        TEXT NOT NULL,                -- PLACED/FILLED/REJECTED/CANCELED/EXPIRED
  ts_accept     INTEGER NOT NULL,             -- ms
  ts_update     INTEGER NOT NULL              -- ms
);

CREATE TABLE IF NOT EXISTS fills (
  id            TEXT PRIMARY KEY,             -- venue trade id or engine uuid
  order_id      TEXT NOT NULL,
  venue         TEXT NOT NULL,
  symbol        TEXT NOT NULL,
  side          TEXT NOT NULL,
  qty           REAL NOT NULL,
  price         REAL NOT NULL,
  fee_ccy       TEXT,
  fee           REAL,
  ts            INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
  venue         TEXT NOT NULL,
  symbol        TEXT NOT NULL,
  net_qty       REAL NOT NULL,
  avg_price     REAL,
  updated_ms    INTEGER NOT NULL,
  PRIMARY KEY (venue, symbol)
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
  venue         TEXT NOT NULL,
  equity_usd    REAL NOT NULL,
  cash_usd      REAL NOT NULL,
  upnl_usd      REAL NOT NULL,
  ts            INTEGER NOT NULL,
  PRIMARY KEY (venue, ts)
);
