"""
loader.py  ─  Stage 3 & 4: Analyse + Visualise
Reads data/cleaned.csv, generates all charts, saves PNGs to reports/
"""
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
import seaborn as sns
from pathlib import Path
from datetime import datetime

from config import CLEANED_CSV, REPORTS_DIR
from logger import get_logger

log = get_logger("loader")

PALETTE   = ["#0A84FF", "#30D158", "#FF453A", "#FF9F0A", "#BF5AF2",
             "#64D2FF", "#FFD60A", "#FF6B6B", "#4ECDC4", "#45B7D1"]
BG_COLOR  = "#0D1117"
TEXT_CLR  = "#E6EDF3"
GRID_CLR  = "#21262D"
UP_CLR    = "#26a69a"
DOWN_CLR  = "#ef5350"

plt.rcParams.update({
    "figure.facecolor":  BG_COLOR,
    "axes.facecolor":    BG_COLOR,
    "axes.edgecolor":    GRID_CLR,
    "axes.labelcolor":   TEXT_CLR,
    "text.color":        TEXT_CLR,
    "xtick.color":       TEXT_CLR,
    "ytick.color":       TEXT_CLR,
    "grid.color":        GRID_CLR,
    "grid.alpha":        0.5,
    "legend.facecolor":  "#161B22",
    "legend.edgecolor":  GRID_CLR,
    "font.family":       "DejaVu Sans",
})


def load_cleaned() -> pd.DataFrame:
    if not CLEANED_CSV.exists():
        raise FileNotFoundError(f"cleaned.csv not found at {CLEANED_CSV}")
    df = pd.read_csv(CLEANED_CSV, parse_dates=["fetched_at", "date"])
    log.info(f"Loaded cleaned.csv: {len(df)} rows")
    return df


# ─── Chart 1: Close Price Line Chart (all symbols) ───────────────────────────

def plot_close_lines(df: pd.DataFrame) -> Path:
    symbols = [s for s in df["symbol"].unique() if s != "NEPSE"][:8]
    fig, ax = plt.subplots(figsize=(14, 7))

    for i, sym in enumerate(symbols):
        sub = df[df["symbol"] == sym].sort_values("fetched_at")
        if sub.empty:
            continue
        ax.plot(sub["fetched_at"], sub["close"],
                label=sym, color=PALETTE[i % len(PALETTE)],
                linewidth=1.8, marker="o", markersize=3)

    ax.set_title("NEPSE  ·  Close Price Over Fetched Sessions",
                 fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Fetched At (NPT)")
    ax.set_ylabel("Close Price (NPR)")
    ax.legend(loc="upper left", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"Rs {x:,.0f}"))

    out = REPORTS_DIR / "01_close_price_lines.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Chart 2: Bar Chart – Pct Change per Symbol ──────────────────────────────

def plot_pct_change_bars(df: pd.DataFrame) -> Path:
    # Latest row per symbol
    latest = (df.sort_values("fetched_at")
                .groupby("symbol")
                .last()
                .reset_index()
                .sort_values("pct_change_calc"))

    colors = [UP_CLR if v >= 0 else DOWN_CLR for v in latest["pct_change_calc"]]

    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.barh(latest["symbol"], latest["pct_change_calc"],
                   color=colors, edgecolor="none", height=0.6)

    for bar, val in zip(bars, latest["pct_change_calc"]):
        sign = "+" if val >= 0 else ""
        ax.text(val + (0.05 if val >= 0 else -0.05),
                bar.get_y() + bar.get_height() / 2,
                f"{sign}{val:.2f}%",
                va="center", ha="left" if val >= 0 else "right",
                fontsize=8, color=TEXT_CLR)

    ax.axvline(0, color=GRID_CLR, linewidth=1)
    ax.set_title("Latest % Change  ·  All Symbols", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("% Change from Previous Close")
    ax.grid(True, axis="x", linestyle="--", alpha=0.4)

    out = REPORTS_DIR / "02_pct_change_bars.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Chart 3: Candlestick (top 4 traded symbols) ─────────────────────────────

def plot_candlestick(df: pd.DataFrame) -> Path:
    # Pick symbols with most rows
    top_syms = (df.groupby("symbol")["symbol"].count()
                  .nlargest(4).index.tolist())

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    axes = axes.flatten()

    for ax_i, sym in enumerate(top_syms):
        ax = axes[ax_i]
        sub = (df[df["symbol"] == sym]
               .sort_values("fetched_at")
               .reset_index(drop=True))

        if sub.empty or len(sub) < 2:
            ax.text(0.5, 0.5, f"{sym}\nNo data", transform=ax.transAxes,
                    ha="center", va="center", color=TEXT_CLR)
            continue

        # Use integer x-axis for positioning
        x = np.arange(len(sub))
        width = 0.4

        for i, row in sub.iterrows():
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            clr = UP_CLR if c >= o else DOWN_CLR

            # Wick
            ax.plot([i, i], [l, h], color=clr, linewidth=1)
            # Body
            body_h = abs(c - o) if abs(c - o) > 0 else 0.1
            rect = Rectangle(
                (i - width / 2, min(o, c)),
                width, body_h,
                facecolor=clr, edgecolor=clr, linewidth=0.5,
            )
            ax.add_patch(rect)

        ax.set_xlim(-0.5, len(sub) - 0.5)
        lo = sub["low"].min()
        hi = sub["high"].max()
        margin = (hi - lo) * 0.05
        ax.set_ylim(lo - margin, hi + margin)

        # X labels: time
        tick_idx = list(range(0, len(sub), max(1, len(sub) // 5)))
        ax.set_xticks(tick_idx)
        ax.set_xticklabels(
            [sub["fetched_at"].iloc[i].strftime("%H:%M") for i in tick_idx],
            rotation=30, fontsize=7,
        )
        ax.set_title(f"{sym}", fontsize=11, fontweight="bold")
        ax.set_ylabel("NPR")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.grid(True, linestyle="--", alpha=0.3)

    # Hide unused axes
    for j in range(len(top_syms), 4):
        axes[j].set_visible(False)

    fig.suptitle("Candlestick Charts  ·  Top Traded Symbols",
                 fontsize=15, fontweight="bold", y=1.01)
    fig.tight_layout()

    out = REPORTS_DIR / "03_candlestick.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Chart 4: Volume Bar Chart ────────────────────────────────────────────────

def plot_volume(df: pd.DataFrame) -> Path:
    top_syms = (df.groupby("symbol")["volume"].sum()
                  .nlargest(8).index.tolist())
    sub = df[df["symbol"].isin(top_syms)]

    latest_vol = (sub.groupby("symbol")["volume"].sum()
                     .sort_values(ascending=True))

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(latest_vol))]
    bars = ax.barh(latest_vol.index, latest_vol.values,
                   color=colors, edgecolor="none", height=0.6)

    for bar, val in zip(bars, latest_vol.values):
        ax.text(val + latest_vol.max() * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f}",
                va="center", fontsize=8, color=TEXT_CLR)

    ax.set_title("Total Volume (Session)  ·  Top Symbols",
                 fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Total Shares Traded")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.grid(True, axis="x", linestyle="--", alpha=0.4)

    out = REPORTS_DIR / "04_volume_bars.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Chart 5: Heatmap – Correlation of % Change ──────────────────────────────

def plot_correlation_heatmap(df: pd.DataFrame) -> Path:
    pivot = (df.pivot_table(
                index="fetched_at", columns="symbol",
                values="pct_change_calc", aggfunc="last")
               .dropna(axis=1, thresh=2))

    if pivot.shape[1] < 2:
        log.warning("Not enough symbols for correlation heatmap — skipping")
        return None

    corr = pivot.corr()

    fig, ax = plt.subplots(figsize=(10, 8))
    mask = np.triu(np.ones_like(corr, dtype=bool))
    cmap = sns.diverging_palette(10, 130, as_cmap=True)
    sns.heatmap(corr, mask=mask, cmap=cmap, center=0,
                annot=True, fmt=".2f", annot_kws={"size": 8},
                linewidths=0.5, linecolor=GRID_CLR,
                ax=ax, cbar_kws={"shrink": 0.8})

    ax.set_title("% Change Correlation  ·  All Symbols",
                 fontsize=14, fontweight="bold", pad=12)
    ax.tick_params(axis="x", rotation=45)

    out = REPORTS_DIR / "05_correlation_heatmap.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Chart 6: Cumulative Return ──────────────────────────────────────────────

def plot_cumulative_return(df: pd.DataFrame) -> Path:
    symbols = [s for s in df["symbol"].unique() if s != "NEPSE"][:6]
    fig, ax = plt.subplots(figsize=(14, 6))

    for i, sym in enumerate(symbols):
        sub = df[df["symbol"] == sym].sort_values("fetched_at")
        if sub.empty:
            continue
        ax.plot(sub["fetched_at"], sub["cum_return_pct"],
                label=sym, color=PALETTE[i % len(PALETTE)],
                linewidth=2)

    ax.axhline(0, color=GRID_CLR, linewidth=1, linestyle="--")
    ax.set_title("Cumulative % Return  ·  Session",
                 fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Fetched At (NPT)")
    ax.set_ylabel("Cumulative Return (%)")
    ax.legend(loc="upper left", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    ax.grid(True, linestyle="--", alpha=0.4)

    out = REPORTS_DIR / "06_cumulative_return.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Chart 7: OHLCV Summary Table Chart ──────────────────────────────────────

def plot_summary_table(df: pd.DataFrame) -> Path:
    latest = (df.sort_values("fetched_at")
                .groupby("symbol")
                .last()
                .reset_index()[["symbol", "open", "high", "low", "close",
                                "volume", "pct_change_calc"]]
                .sort_values("pct_change_calc", ascending=False))

    latest.columns = ["Symbol", "Open", "High", "Low", "Close", "Volume", "Chg%"]
    for col in ("Open", "High", "Low", "Close"):
        latest[col] = latest[col].map(lambda x: f"Rs {x:,.2f}")
    latest["Volume"] = latest["Volume"].map(lambda x: f"{x:,}")
    latest["Chg%"]   = latest["Chg%"].map(lambda x: f"{'+' if x >= 0 else ''}{x:.2f}%")

    fig, ax = plt.subplots(figsize=(14, max(4, len(latest) * 0.45 + 1)))
    ax.axis("off")

    tbl = ax.table(
        cellText=latest.values,
        colLabels=latest.columns,
        cellLoc="center",
        loc="center",
        bbox=[0, 0, 1, 1],
    )

    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)

    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor(GRID_CLR)
        if row == 0:
            cell.set_facecolor("#1C2128")
            cell.set_text_props(color=TEXT_CLR, fontweight="bold")
        elif row % 2 == 0:
            cell.set_facecolor("#161B22")
            cell.set_text_props(color=TEXT_CLR)
        else:
            cell.set_facecolor("#0D1117")
            cell.set_text_props(color=TEXT_CLR)

        # Colour Chg% column
        if col == 6 and row > 0:
            val = latest.iloc[row - 1]["Chg%"]
            cell.set_text_props(color=UP_CLR if "+" in val else DOWN_CLR)

    ax.set_title("NEPSE  ·  Session Summary Table",
                 fontsize=14, fontweight="bold", pad=12, color=TEXT_CLR)

    out = REPORTS_DIR / "07_summary_table.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Chart 8: NEPSE Index Line ────────────────────────────────────────────────

def plot_nepse_index(df: pd.DataFrame) -> Path:
    nepse = df[df["symbol"] == "NEPSE"].sort_values("fetched_at")
    if nepse.empty:
        log.warning("No NEPSE index data — skipping index chart")
        return None

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9),
                                    gridspec_kw={"height_ratios": [3, 1]},
                                    sharex=True)

    # Price
    ax1.plot(nepse["fetched_at"], nepse["close"],
             color="#0A84FF", linewidth=2)
    ax1.fill_between(nepse["fetched_at"], nepse["close"],
                     alpha=0.15, color="#0A84FF")
    ax1.set_title("NEPSE Index  ·  Intraday", fontsize=14, fontweight="bold", pad=10)
    ax1.set_ylabel("Index Value")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax1.grid(True, linestyle="--", alpha=0.4)

    # Volume
    colors_v = [UP_CLR if r >= 0 else DOWN_CLR
                for r in nepse["pct_change_calc"]]
    ax2.bar(nepse["fetched_at"], nepse["volume"],
            color=colors_v, width=0.002, alpha=0.8)
    ax2.set_ylabel("Volume")
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax2.grid(True, linestyle="--", alpha=0.4)

    fig.autofmt_xdate()
    fig.tight_layout()

    out = REPORTS_DIR / "08_nepse_index.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Generate all charts ──────────────────────────────────────────────────────

def generate_all_charts(df: pd.DataFrame) -> dict[str, Path]:
    charts = {}
    fns = [
        ("close_lines",        plot_close_lines),
        ("pct_change_bars",    plot_pct_change_bars),
        ("candlestick",        plot_candlestick),
        ("volume",             plot_volume),
        ("correlation",        plot_correlation_heatmap),
        ("cumulative_return",  plot_cumulative_return),
        ("summary_table",      plot_summary_table),
        ("nepse_index",        plot_nepse_index),
    ]
    for key, fn in fns:
        try:
            path = fn(df)
            if path:
                charts[key] = path
        except Exception as e:
            log.error(f"Chart '{key}' failed: {e}", exc_info=True)
    return charts


if __name__ == "__main__":
    df = load_cleaned()
    charts = generate_all_charts(df)
    print(f"Generated {len(charts)} chart(s):")
    for k, p in charts.items():
        print(f"  {k}: {p}")
