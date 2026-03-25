"""
transformer.py  ─  Stage 2: Transform & Enrich
Reads data/raw.csv → cleans → enriches → writes data/cleaned.csv

No date filtering is applied — all rows currently in raw.csv are transformed.
Call this any time and it works against the latest session data.
"""
import pandas as pd
import numpy as np
from pathlib import Path

from config import RAW_CSV, CLEANED_CSV
from logger import get_logger

log = get_logger("transformer")


class DataCleaningPipeline:
    """
    A simple step-by-step data pipeline.
    You add steps with .add(), then call .run() to execute them in order.
    Each step is a function that takes a DataFrame and returns a DataFrame.
    """
    def __init__(self, df: pd.DataFrame):
        self.df    = df.copy()
        self._steps: list[tuple[str, callable]] = []

    def add(self, name: str, fn: callable) -> "DataCleaningPipeline":
        self._steps.append((name, fn))
        return self  # allows chaining: pipeline.add(...).add(...)

    def run(self) -> pd.DataFrame:
        for name, fn in self._steps:
            log.info(f"Running step: {name}")
            self.df = fn(self.df)
            if self.df.empty:
                raise ValueError(f"Step '{name}' produced empty DataFrame")
            log.debug(f"  → {len(self.df)} rows OK")
        return self.df


def transform(raw_path: Path = RAW_CSV,
              out_path: Path = CLEANED_CSV) -> pd.DataFrame:
    """
    Read raw.csv and produce cleaned.csv with extra computed columns.
    Raises FileNotFoundError if raw.csv doesn't exist.
    Raises ValueError if raw.csv is empty.
    """
    if not raw_path.exists():
        raise FileNotFoundError(raw_path)

    df = pd.read_csv(raw_path)
    if df.empty:
        raise ValueError("raw.csv is empty")

    log.info(
        f"Loaded raw.csv: {len(df)} rows, "
        f"{df['symbol'].nunique()} symbol(s), "
        f"dates: {sorted(df['date'].unique()) if 'date' in df.columns else '?'}"
    )

    # ── Step 1: Fix data types ─────────────────────────────────────────────────
    def coerce_types(df):
        df["fetched_at"] = pd.to_datetime(df["fetched_at"], errors="coerce")
        df["date"]       = pd.to_datetime(df["date"],       errors="coerce")
        for col in ("open", "high", "low", "close", "prev_close", "pct_change",
                    "ma5", "ma10", "ma20"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
        return df

    # ── Step 2: Remove duplicate rows ─────────────────────────────────────────
    def drop_duplicates(df):
        before = len(df)
        df = df.drop_duplicates(subset=["symbol", "fetched_at"])
        log.info(f"  drop_duplicates removed {before - len(df)} rows")
        return df

    # ── Step 3: Drop rows where OHLC price data is missing ────────────────────
    def drop_null_ohlcv(df):
        before = len(df)
        df = df.dropna(subset=["open", "high", "low", "close"])
        log.info(f"  drop_null_ohlcv removed {before - len(df)} rows")
        return df

    # ── Step 4: Remove rows that violate basic OHLC rules ─────────────────────
    # E.g. high can't be lower than low, close can't be negative
    def sanity_checks(df):
        before = len(df)
        df = df[
            (df["high"]   >= df["low"])   &
            (df["high"]   >= df["open"])  &
            (df["high"]   >= df["close"]) &
            (df["low"]    <= df["open"])  &
            (df["low"]    <= df["close"]) &
            (df["close"]  >  0)           &
            (df["volume"] >= 0)
        ]
        log.info(f"  sanity_checks removed {before - len(df)} invalid rows")
        return df

    # ── Step 5: Fill in prev_close from the previous row if missing ───────────
    def derive_prev_close(df):
        df = df.sort_values(["symbol", "fetched_at"]).reset_index(drop=True)
        df["prev_close_derived"] = df.groupby("symbol")["close"].shift(1)
        # For the first row of each symbol, fall back to the raw prev_close
        mask = df["prev_close_derived"].isna()
        df.loc[mask, "prev_close_derived"] = df.loc[mask, "prev_close"]
        return df

    # ── Step 6: Compute derived/extra columns ─────────────────────────────────
    def feature_engineering(df):
        # More accurate % change (recalculated from clean data)
        df["pct_change_calc"] = np.where(
            df["prev_close_derived"] > 0,
            (df["close"] - df["prev_close_derived"]) / df["prev_close_derived"] * 100,
            df["pct_change"],
        ).round(2)

        # Candle geometry
        df["range"]        = (df["high"] - df["low"]).round(2)
        df["range_pct"]    = (df["range"] / df["low"] * 100).round(2)
        df["body"]         = (df["close"] - df["open"]).round(2)
        df["upper_shadow"] = (df["high"] - df[["open", "close"]].max(axis=1)).round(2)
        df["lower_shadow"] = (df[["open", "close"]].min(axis=1) - df["low"]).round(2)
        df["direction"]    = np.where(df["close"] >= df["open"], "UP", "DOWN")

        # Normalised close price (0–1 scale per symbol, useful for comparison)
        df["close_scaled"] = (
            df.groupby("symbol")["close"]
              .transform(lambda x: (x - x.min()) / (x.max() - x.min() + 1e-9))
              .round(4)
        )

        # Cumulative % return since session start, per symbol
        df["cum_return_pct"] = (
            df.groupby("symbol")["pct_change_calc"]
              .transform("cumsum")
              .round(2)
        )

        df["fetch_hour"] = df["fetched_at"].dt.hour

        # Recompute moving averages from clean sorted data
        for n, col in [(5, "ma5"), (10, "ma10"), (20, "ma20")]:
            computed = (
                df.groupby("symbol")["close"]
                  .transform(lambda x: x.rolling(n, min_periods=1).mean().round(2))
            )
            df[col] = df[col].fillna(computed) if col in df.columns else computed

        return df

    # ── Step 7: Fill any remaining NaN with 0 ─────────────────────────────────
    def fill_nulls(df):
        df["pct_change_calc"] = df["pct_change_calc"].fillna(0.0)
        df["cum_return_pct"]  = df["cum_return_pct"].fillna(0.0)
        return df

    # ── Run all steps ──────────────────────────────────────────────────────────
    pipeline = (
        DataCleaningPipeline(df)
        .add("coerce_types",       coerce_types)
        .add("drop_duplicates",    drop_duplicates)
        .add("drop_null_ohlcv",    drop_null_ohlcv)
        .add("sanity_checks",      sanity_checks)
        .add("derive_prev_close",  derive_prev_close)
        .add("feature_engineering", feature_engineering)
        .add("fill_nulls",         fill_nulls)
    )

    cleaned = pipeline.run()
    cleaned = cleaned.sort_values(["symbol", "fetched_at"]).reset_index(drop=True)

    cleaned.to_csv(out_path, index=False)
    log.info(f"Saved cleaned.csv: {len(cleaned)} rows → {out_path}")
    return cleaned


if __name__ == "__main__":
    df = transform()
    print(df.head(20).to_string())
    print(f"\nShape: {df.shape}")
    print(f"Symbols: {df['symbol'].unique()}")
