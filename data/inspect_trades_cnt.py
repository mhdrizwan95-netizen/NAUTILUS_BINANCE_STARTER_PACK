
import sqlite3
import pandas as pd
from datetime import datetime

DB_PATH = "/app/data/runtime/trades.db"

def inspect():
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # 1. Count Fills
        print("--- Trade Counts ---")
        cursor = conn.execute("SELECT count(*) FROM fills")
        fill_count = cursor.fetchone()[0]
        print(f"Total Fills: {fill_count}")

        # 2. Recent Fills
        print("\n--- Recent Fills (Last 5) ---")
        cursor = conn.execute("SELECT * FROM fills ORDER BY ts DESC LIMIT 5")
        cols = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        for row in rows:
            # Convert TS (ms) to readable
            ts = row[cols.index("ts")]
            print(f"{datetime.fromtimestamp(ts/1000).isoformat()} | {dict(zip(cols, row))}")

        # 3. Equity Curve
        print("\n--- Recent Equity Snapshots (Last 5) ---")
        cursor = conn.execute("SELECT * FROM equity_snapshots ORDER BY ts DESC LIMIT 5")
        cols = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        for row in rows:
            ts = row[cols.index("ts")]
            print(f"{datetime.fromtimestamp(ts/1000).isoformat()} | {dict(zip(cols, row))}")

        # 4. Approximate PnL from Closed Positions (Round Trips)
        # Assuming FIFO closure for simplicity if not tracked elsewhere
        # Actually, let's just look at 'fills' and sum up? No, fills are separate buys/sells.
        # Let's check 'positions' table if it exists
        try:
            print("\n--- Current Positions ---")
            cursor = conn.execute("SELECT * FROM positions")
            cols = [description[0] for description in cursor.description]
            for row in cursor.fetchall():
                print(dict(zip(cols, row)))
        except sqlite3.OperationalError:
            print("No 'positions' table found.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    inspect()
