import os
from pathlib import Path

import pandas as pd
from loguru import logger

from services.common import manifest

from .config import settings


class HistoricalDriver:
    """
    Feeds the ledger as if bars are arriving in real-time,
    by slicing CSVs in RESEARCH_DIR into chunks and copying them into DATA_INCOMING.
    """

    def __init__(self, symbol: str, timeframe: str):
        self.symbol = symbol
        self.timeframe = timeframe
        self.src_files = sorted(
            (Path(settings.RESEARCH_DIR) / symbol.replace("/", "_") / timeframe).glob("*.csv")
        )
        if not self.src_files:
            logger.warning(f"No research files at {settings.RESEARCH_DIR}/{symbol}/{timeframe}")
        self.src_idx = 0
        self.offset = 0  # row index within current file

        Path(settings.DATA_INCOMING).mkdir(parents=True, exist_ok=True)
        manifest.init(settings.LEDGER_DB)

    def feed_next_chunk(self):
        """
        Copy the next CHUNK_ROWS rows from research CSVs into an 'incoming' CSV and register in ledger.
        Returns the chunk dataframe when available, otherwise None when out of data.
        """
        chunk_rows = settings.CHUNK_ROWS
        while self.src_idx < len(self.src_files):
            src = self.src_files[self.src_idx]
            df = pd.read_csv(src)
            if "timestamp" not in df.columns:
                df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)
            # optional START/END cuts
            if settings.START_TS and settings.START_TS > 0:
                df = df[df["timestamp"] >= settings.START_TS]
            if settings.END_TS and settings.END_TS > 0:
                df = df[df["timestamp"] <= settings.END_TS]
            if self.offset >= len(df):
                # move to next file
                self.src_idx += 1
                self.offset = 0
                continue

            end = min(self.offset + chunk_rows, len(df))
            part = df.iloc[self.offset : end].copy()
            if part.empty:
                self.src_idx += 1
                self.offset = 0
                continue

            t_start = int(part["timestamp"].min())
            t_end = int(part["timestamp"].max())
            dst_dir = Path(settings.DATA_INCOMING) / self.symbol.replace("/", "_") / self.timeframe
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = (
                dst_dir / f"{self.symbol.replace('/','_')}__{self.timeframe}__{t_start}_{t_end}.csv"
            )
            part.to_csv(dst, index=False)

            # register with ledger (dedup by sha256)
            file_id, inserted = manifest.register_file(
                str(dst),
                self.symbol,
                self.timeframe,
                t_start,
                t_end,
                db_path=settings.LEDGER_DB,
            )
            if not inserted:
                try:
                    os.remove(dst)
                except FileNotFoundError:
                    pass
            else:
                self.offset = end
                return part
        return None
