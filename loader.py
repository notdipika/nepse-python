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
"""
loader.py  ─  Stage 3 & 4: Analyse + Visualise
Reads data/cleaned.csv → charts into  reports/YYYY-MM-DD/graphs/

v2 improvements:
  • Moving average overlays (MA5, MA10, MA20) on every individual chart
  • MA legend added per chart
  • Soft warm palette unchanged
"""
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.patches import Rectangle
import seaborn as sns
from pathlib import Path

from config import CLEANED_CSV, get_session_dirs
from logger import get_logger

log = get_logger("loader")

# ─── Soft warm palette ────────────────────────────────────────────────────────
SOFT_PALETTE = [
    "#5B8DB8", "#E07B54", "#6AAB8E", "#C27BAD", "#D4A843",
    "#7B9EC4", "#E0956B", "#7DC4A8", "#BA8FC2", "#8BAD6A",
]

BG     = "#FAFAF8"
PANEL  = "#F4F1ED"
BORDER = "#DDD8D0"
TEXT   = "#2C2C2C"
MUTED  = "#8A8680"
UP_C   = "#4E9E7A"
DOWN_C = "#C96A5A"
GRID_C = "#EAE6E0"

MA_COLORS = {"ma5": "#F4A261", "ma10": "#E76F51", "ma20": "#264653"}

plt.rcParams.update({
    "figure.facecolor":  BG,
    "axes.facecolor":    PANEL,
    "axes.edgecolor":    BORDER,
    "axes.labelcolor":   TEXT,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "text.color":        TEXT,
    "xtick.color":       MUTED,
    "ytick.color":       MUTED,
    "xtick.labelsize":   8,
    "ytick.labelsize":   8,
    "grid.color":        GRID_C,
    "grid.linewidth":    0.7,
    "legend.facecolor":  BG,
    "legend.edgecolor":  BORDER,
    "legend.fontsize":   8,
    "font.family":       "DejaVu Sans",
    "font.size":         9,
})

FOOTER = "Source: merolagani.com  ·  NEPSE ETL Pipeline  ·  For informational purposes only"


def load_cleaned() -> pd.DataFrame:
    if not CLEANED_CSV.exists():
        raise FileNotFoundError(f"cleaned.csv not found at {CLEANED_CSV}")
    df = pd.read_csv(CLEANED_CSV, parse_dates=["fetched_at", "date"])
    log.info(f"Loaded cleaned.csv: {len(df)} rows")
    return df


def _fmt_npr(ax):
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"Rs {x:,.0f}"))


def _shade(ax, x, y, color):
    ax.fill_between(x, y, float(y.min()) * 0.9995,
                    alpha=0.09, color=color, linewidth=0)


def _trend_badge(ax, y_vals, color):
    if len(y_vals) < 2:
        return
    first, last = float(y_vals.iloc[0]), float(y_vals.iloc[-1])
    pct = (last - first) / first * 100 if first > 0 else 0
    if abs(pct) < 0.3:
        txt, c = "→  Flat session", MUTED
    elif pct > 0:
        txt, c = f"↑  +{pct:.2f}%  net gain", UP_C
    else:
        txt, c = f"↓  {pct:.2f}%  net loss", DOWN_C
    ax.text(0.985, 0.965, txt,
            transform=ax.transAxes, ha="right", va="top",
            fontsize=8.5, color=c, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.35", facecolor=BG,
                      edgecolor=c, alpha=0.9, linewidth=0.9))


def _mark_hl(ax, x, y):
    if len(y) < 3:
        return
    ih = y.idxmax(); il = y.idxmin()
    ax.annotate(f"H  Rs {y[ih]:,.0f}",
                xy=(x[ih], y[ih]), xytext=(0, 14),
                textcoords="offset points",
                ha="center", fontsize=7, color=UP_C,
                arrowprops=dict(arrowstyle="-", color=UP_C, lw=0.7))
    ax.annotate(f"L  Rs {y[il]:,.0f}",
                xy=(x[il], y[il]), xytext=(0, -16),
                textcoords="offset points",
                ha="center", fontsize=7, color=DOWN_C,
                arrowprops=dict(arrowstyle="-", color=DOWN_C, lw=0.7))


def _plot_ma_overlays(ax, sub: pd.DataFrame, line_color: str):
    """Draw MA5, MA10, MA20 lines on price axis if enough data exists."""
    ma_handles = []
    for col, label, lw, ls in [
        ("ma5",  "MA 5",  1.4, "--"),
        ("ma10", "MA 10", 1.4, "-."),
        ("ma20", "MA 20", 1.6, ":"),
    ]:
        if col in sub.columns:
            valid = sub[["fetched_at", col]].dropna()
            if len(valid) >= 2:
                line, = ax.plot(valid["fetched_at"], valid[col],
                                color=MA_COLORS.get(col, MUTED),
                                linewidth=lw, linestyle=ls,
                                alpha=0.85, zorder=2, label=label)
                ma_handles.append(line)
    return ma_handles


# ─── Per-company line chart ───────────────────────────────────────────────────

def plot_individual_lines(df: pd.DataFrame,
                          graphs_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    symbols = df["symbol"].unique()

    for i, sym in enumerate(symbols):
        sub = (df[df["symbol"] == sym]
               .sort_values("fetched_at")
               .reset_index(drop=True))
        if len(sub) < 2:
            continue

        color = SOFT_PALETTE[i % len(SOFT_PALETTE)]

        fig, (ax_p, ax_v) = plt.subplots(
            2, 1, figsize=(11, 6.5),
            gridspec_kw={"height_ratios": [3, 1], "hspace": 0.07},
            sharex=True,
        )
        fig.patch.set_facecolor(BG)

        # Price line
        price_line, = ax_p.plot(sub["fetched_at"], sub["close"],
                                color=color, linewidth=2.4,
                                solid_capstyle="round", zorder=3, label="Close")
        _shade(ax_p, sub["fetched_at"], sub["close"], color)
        ax_p.scatter([sub["fetched_at"].iloc[-1]], [sub["close"].iloc[-1]],
                     color=color, s=45, zorder=4,
                     edgecolors=BG, linewidth=1.8)

        _mark_hl(ax_p, sub["fetched_at"], sub["close"])
        _trend_badge(ax_p, sub["close"], color)

        # MA overlays
        ma_handles = _plot_ma_overlays(ax_p, sub, color)

        # Legend (close + MAs)
        if ma_handles:
            ax_p.legend(handles=[price_line] + ma_handles,
                        loc="upper left", framealpha=0.85, fontsize=7.5)

        close_last = sub["close"].iloc[-1]
        pct_last   = float(sub["pct_change_calc"].iloc[-1]) \
                     if "pct_change_calc" in sub.columns else 0.0
        sign = "+" if pct_last >= 0 else ""

        ax_p.set_title(f"{sym}  ·  Close Price  —  Intraday Session",
                       fontsize=13, fontweight="bold", color=TEXT,
                       loc="left", pad=10)
        ax_p.text(
            0.0, 1.015,
            f"Last close: Rs {close_last:,.2f}   |   "
            f"Change: {sign}{pct_last:.2f}%   |   "
            f"Session high: Rs {sub['high'].max():,.2f}   |   "
            f"Session low: Rs {sub['low'].min():,.2f}   |   "
            f"Volume: {int(sub['volume'].iloc[-1]):,}",
            transform=ax_p.transAxes,
            fontsize=7.5, color=MUTED, va="bottom",
        )

        _fmt_npr(ax_p)
        ax_p.set_ylabel("Price (NPR)", fontsize=8, color=MUTED)
        ax_p.grid(True, axis="y", linestyle="--")

        # Volume
        v_cols = [UP_C if r >= 0 else DOWN_C
                  for r in sub.get("pct_change_calc",
                                   pd.Series([0] * len(sub)))]
        ax_v.bar(sub["fetched_at"], sub["volume"],
                 color=v_cols, alpha=0.5, width=0.003)
        ax_v.set_ylabel("Volume", fontsize=7, color=MUTED)
        ax_v.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}K"))
        ax_v.grid(True, axis="y", linestyle="--")
        ax_v.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax_v.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax_v.xaxis.get_majorticklabels(), rotation=30, ha="right")
        ax_v.set_xlabel("Time (NPT)", fontsize=8, color=MUTED)

        fig.text(0.01, 0.005, FOOTER, fontsize=6, color=MUTED)
        fig.tight_layout(rect=[0, 0.02, 1, 1])

        out = graphs_dir / f"line_{sym}.png"
        fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        paths[sym] = out
        log.info(f"Saved individual line chart: {out.name}")

    return paths


# ─── Overlay ─────────────────────────────────────────────────────────────────

def plot_close_overlay(df: pd.DataFrame, graphs_dir: Path) -> Path:
    symbols = [s for s in df["symbol"].unique() if s != "NEPSE"][:8]
    fig, ax = plt.subplots(figsize=(13, 6))
    for i, sym in enumerate(symbols):
        sub = df[df["symbol"] == sym].sort_values("fetched_at")
        if sub.empty: continue
        ax.plot(sub["fetched_at"], sub["close"],
                label=sym, color=SOFT_PALETTE[i % len(SOFT_PALETTE)],
                linewidth=1.9, marker="o", markersize=2.5, solid_capstyle="round")
    ax.set_title("All Symbols  ·  Close Price Overlay",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=10)
    ax.set_xlabel("Time (NPT)", fontsize=8, color=MUTED)
    ax.set_ylabel("Close Price (NPR)", fontsize=8, color=MUTED)
    ax.legend(ncol=2, framealpha=0.9)
    _fmt_npr(ax)
    ax.grid(True, linestyle="--")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout()
    out = graphs_dir / "overlay_close_lines.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── % Change bars ────────────────────────────────────────────────────────────

def plot_pct_change_bars(df: pd.DataFrame, graphs_dir: Path) -> Path:
    latest = (df.sort_values("fetched_at").groupby("symbol").last()
                .reset_index().sort_values("pct_change_calc"))
    bar_colors = [UP_C if v >= 0 else DOWN_C for v in latest["pct_change_calc"]]
    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.barh(latest["symbol"], latest["pct_change_calc"],
                   color=bar_colors, edgecolor="none", height=0.55, alpha=0.85)
    offset = latest["pct_change_calc"].abs().max() * 0.02
    for bar, val in zip(bars, latest["pct_change_calc"]):
        sign = "+" if val >= 0 else ""
        ax.text(val + (offset if val >= 0 else -offset),
                bar.get_y() + bar.get_height() / 2,
                f"{sign}{val:.2f}%", va="center",
                ha="left" if val >= 0 else "right",
                fontsize=8, color=TEXT)
    ax.axvline(0, color=BORDER, linewidth=1)
    ax.set_title("Latest % Change vs Previous Close",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=10)
    ax.set_xlabel("% Change", fontsize=8, color=MUTED)
    ax.grid(True, axis="x", linestyle="--")
    n_up   = (latest["pct_change_calc"] > 0).sum()
    n_down = (latest["pct_change_calc"] < 0).sum()
    ax.text(0.99, 0.02, f"{n_up} gainers  ·  {n_down} losers",
            transform=ax.transAxes, ha="right", va="bottom",
            fontsize=8, color=MUTED,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=BG,
                      edgecolor=BORDER, alpha=0.9))
    fig.tight_layout()
    out = graphs_dir / "pct_change_bars.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Candlestick ──────────────────────────────────────────────────────────────

def plot_candlestick(df: pd.DataFrame, graphs_dir: Path) -> Path:
    top_syms = df.groupby("symbol")["symbol"].count().nlargest(4).index.tolist()
    fig, axes = plt.subplots(2, 2, figsize=(15, 9))
    axes = axes.flatten()
    for ai, sym in enumerate(top_syms):
        ax  = axes[ai]
        sub = df[df["symbol"] == sym].sort_values("fetched_at").reset_index(drop=True)
        if len(sub) < 2:
            ax.text(0.5, 0.5, f"{sym}\nNo data", transform=ax.transAxes,
                    ha="center", va="center", color=MUTED); continue
        for i, row in sub.iterrows():
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            clr = UP_C if c >= o else DOWN_C
            ax.plot([i, i], [l, h], color=clr, linewidth=0.9, zorder=2)
            rect = Rectangle((i - 0.3, min(o, c)), 0.6, max(abs(c - o), 0.1),
                              facecolor=clr, edgecolor=clr, alpha=0.85,
                              linewidth=0.4, zorder=3)
            ax.add_patch(rect)
        ax.set_xlim(-0.5, len(sub) - 0.5)
        lo, hi = sub["low"].min(), sub["high"].max()
        m = (hi - lo) * 0.06
        ax.set_ylim(lo - m, hi + m)
        tidx = list(range(0, len(sub), max(1, len(sub) // 5)))
        ax.set_xticks(tidx)
        ax.set_xticklabels([sub["fetched_at"].iloc[j].strftime("%H:%M") for j in tidx],
                           rotation=30, fontsize=7)
        ax.set_title(sym, fontsize=11, fontweight="bold", color=TEXT)
        ax.set_ylabel("NPR", fontsize=8, color=MUTED)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.grid(True, linestyle="--")
    for j in range(len(top_syms), 4):
        axes[j].set_visible(False)
    fig.suptitle("Candlestick Charts  ·  Top Symbols",
                 fontsize=13, fontweight="bold", color=TEXT, y=1.01)
    fig.tight_layout()
    out = graphs_dir / "candlestick.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Volume ───────────────────────────────────────────────────────────────────

def plot_volume(df: pd.DataFrame, graphs_dir: Path) -> Path:
    top = df.groupby("symbol")["volume"].sum().nlargest(8).index.tolist()
    vs  = df[df["symbol"].isin(top)].groupby("symbol")["volume"].sum().sort_values()
    fig, ax = plt.subplots(figsize=(12, 5))
    bars = ax.barh(vs.index, vs.values,
                   color=[SOFT_PALETTE[i % len(SOFT_PALETTE)] for i in range(len(vs))],
                   edgecolor="none", height=0.55, alpha=0.85)
    for bar, val in zip(bars, vs.values):
        ax.text(val + vs.max() * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,}", va="center", fontsize=8, color=MUTED)
    ax.set_title("Total Session Volume  ·  Top Symbols",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=10)
    ax.set_xlabel("Shares Traded", fontsize=8, color=MUTED)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.grid(True, axis="x", linestyle="--")
    fig.tight_layout()
    out = graphs_dir / "volume_bars.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Correlation heatmap ──────────────────────────────────────────────────────

def plot_correlation_heatmap(df: pd.DataFrame, graphs_dir: Path) -> Path | None:
    pivot = (df.pivot_table(index="fetched_at", columns="symbol",
                            values="pct_change_calc", aggfunc="last")
               .dropna(axis=1, thresh=2))
    if pivot.shape[1] < 2:
        return None
    corr = pivot.corr()
    fig, ax = plt.subplots(figsize=(10, 8))
    mask = np.triu(np.ones_like(corr, dtype=bool))
    sns.heatmap(corr, mask=mask,
                cmap=sns.light_palette("#5B8DB8", as_cmap=True),
                center=0, annot=True, fmt=".2f", annot_kws={"size": 8},
                linewidths=0.5, linecolor=BORDER, ax=ax,
                cbar_kws={"shrink": 0.75})
    ax.set_title("% Change Correlation — All Symbols",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=10)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    out = graphs_dir / "correlation_heatmap.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Cumulative return ────────────────────────────────────────────────────────

def plot_cumulative_return(df: pd.DataFrame, graphs_dir: Path) -> Path:
    symbols = [s for s in df["symbol"].unique() if s != "NEPSE"][:6]
    fig, ax = plt.subplots(figsize=(13, 5))
    for i, sym in enumerate(symbols):
        sub = df[df["symbol"] == sym].sort_values("fetched_at")
        if sub.empty: continue
        ax.plot(sub["fetched_at"], sub["cum_return_pct"],
                label=sym, color=SOFT_PALETTE[i % len(SOFT_PALETTE)],
                linewidth=2, solid_capstyle="round")
    ax.axhline(0, color=BORDER, linewidth=1, linestyle="--")
    ax.set_title("Cumulative Return (%)  ·  Session",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=10)
    ax.set_xlabel("Time (NPT)", fontsize=8, color=MUTED)
    ax.set_ylabel("Cumulative %", fontsize=8, color=MUTED)
    ax.legend(ncol=2); ax.grid(True, linestyle="--")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate(); fig.tight_layout()
    out = graphs_dir / "cumulative_return.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    log.info(f"Saved: {out.name}")
    return out


# ─── Summary table ────────────────────────────────────────────────────────────

def plot_summary_table(df: pd.DataFrame, graphs_dir: Path) -> Path:
    latest = (df.sort_values("fetched_at").groupby("symbol").last().reset_index()
                [["symbol","open","high","low","close","volume","pct_change_calc"]]
                .sort_values("pct_change_calc", ascending=False))
    latest.columns = ["Symbol","Open","High","Low","Close","Volume","Chg%"]
    for c in ("Open","High","Low","Close"):
        latest[c] = latest[c].map(lambda x: f"Rs {x:,.2f}")
    latest["Volume"] = latest["Volume"].map(lambda x: f"{x:,}")
    latest["Chg%"]   = latest["Chg%"].map(lambda x: f"{'+'if x>=0 else ''}{x:.2f}%")
    fig, ax = plt.subplots(figsize=(14, max(4, len(latest)*0.5+1.5)))
    ax.axis("off")
    tbl = ax.table(cellText=latest.values, colLabels=latest.columns,
                   cellLoc="center", loc="center", bbox=[0,0,1,1])
    tbl.auto_set_font_size(False); tbl.set_fontsize(9)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor(BORDER)
        if r == 0:
            cell.set_facecolor("#E8E4DF")
            cell.set_text_props(color=TEXT, fontweight="bold")
        else:
            cell.set_facecolor(BG if r % 2 == 0 else PANEL)
            cell.set_text_props(color=TEXT)
        if c == 6 and r > 0:
            val = latest.iloc[r-1]["Chg%"]
            cell.set_text_props(color=UP_C if "+" in val else DOWN_C, fontweight="bold")
    ax.set_title("NEPSE  ·  Session Summary  ·  Latest OHLCV",
                 fontsize=13, fontweight="bold", color=TEXT, pad=12)
    out = graphs_dir / "summary_table.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig); log.info(f"Saved: {out.name}")
    return out


# ─── NEPSE index ──────────────────────────────────────────────────────────────

def plot_nepse_index(df: pd.DataFrame, graphs_dir: Path) -> Path | None:
    nepse = df[df["symbol"] == "NEPSE"].sort_values("fetched_at")
    if nepse.empty: return None
    color = SOFT_PALETTE[0]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8),
                                    gridspec_kw={"height_ratios":[3,1],"hspace":0.1},
                                    sharex=True)
    ax1.plot(nepse["fetched_at"], nepse["close"],
             color=color, linewidth=2.2, solid_capstyle="round", zorder=3)
    _shade(ax1, nepse["fetched_at"], nepse["close"], color)
    _mark_hl(ax1, nepse["fetched_at"], nepse["close"])
    _trend_badge(ax1, nepse["close"], color)
    _plot_ma_overlays(ax1, nepse, color)
    ax1.set_title("NEPSE Index  ·  Intraday Session",
                  fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=10)
    ax1.set_ylabel("Index Value", fontsize=8, color=MUTED)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,_: f"{x:,.0f}"))
    ax1.grid(True, linestyle="--")
    v_cols = [UP_C if r >= 0 else DOWN_C for r in nepse["pct_change_calc"]]
    ax2.bar(nepse["fetched_at"], nepse["volume"], color=v_cols, alpha=0.55, width=0.002)
    ax2.set_ylabel("Volume", fontsize=7, color=MUTED)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,_: f"{x/1e3:.0f}K"))
    ax2.grid(True, linestyle="--")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate(); fig.tight_layout()
    out = graphs_dir / "nepse_index.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig); log.info(f"Saved: {out.name}")
    return out


# ─── Master generator ─────────────────────────────────────────────────────────

def generate_all_charts(df: pd.DataFrame,
                        date_str: str | None = None) -> dict[str, Path]:
    graphs_dir, _ = get_session_dirs(date_str)
    charts: dict[str, Path] = {}

    individual = plot_individual_lines(df, graphs_dir)
    charts.update({f"line_{sym}": p for sym, p in individual.items()})

    for key, fn in [
        ("overlay",     plot_close_overlay),
        ("pct_bars",    plot_pct_change_bars),
        ("candlestick", plot_candlestick),
        ("volume",      plot_volume),
        ("correlation", plot_correlation_heatmap),
        ("cum_return",  plot_cumulative_return),
        ("summary",     plot_summary_table),
        ("nepse_index", plot_nepse_index),
    ]:
        try:
            p = fn(df, graphs_dir)
            if p:
                charts[key] = p
        except Exception as e:
            log.error(f"Chart '{key}' failed: {e}", exc_info=True)

    log.info(f"Generated {len(charts)} chart(s) in {graphs_dir}")
    return charts


if __name__ == "__main__":
    df = load_cleaned()
    charts = generate_all_charts(df)
    for k, p in charts.items():
        print(f"  {k}: {p.name}")
