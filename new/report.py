"""
report.py  ─  Stage 3–5: Charts → PDF → Notify → Email

This single file replaces the old loader.py + report_generator.py.
It does everything in one place:
  1. Generates all matplotlib charts and saves them as PNG files
  2. Assembles those PNGs into a clean, non-overlapping PDF
  3. Fires a desktop notification
  4. Emails the PDF

Usage (standalone test):
    python report.py
"""

import warnings
warnings.filterwarnings("ignore")

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.patches import Rectangle
import seaborn as sns

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, PageBreak,
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from config import CLEANED_CSV, get_session_dirs
from logger import get_logger

log = get_logger("report")


# ══════════════════════════════════════════════════════════════════════════════
# COLOUR PALETTES
# ══════════════════════════════════════════════════════════════════════════════

# High-contrast chart colours (WCAG-friendly, distinct from each other)
PALETTE = [
    "#1565C0",  # deep blue
    "#D84315",  # burnt orange
    "#2E7D32",  # forest green
    "#6A1B9A",  # deep purple
    "#F57F17",  # amber
    "#00838F",  # teal
    "#AD1457",  # pink-red
    "#4E342E",  # brown
    "#00695C",  # dark teal
    "#283593",  # indigo
]

# Chart backgrounds
BG     = "#FFFFFF"   # pure white background (was warm beige — hard to read on)
PANEL  = "#F5F5F5"   # light grey axes background
BORDER = "#BDBDBD"   # medium grey borders
TEXT   = "#212121"   # near-black text
MUTED  = "#616161"   # grey for labels
GRID_C = "#E0E0E0"   # light grey grid

UP_C   = "#1B5E20"   # dark green for gains
DOWN_C = "#B71C1C"   # dark red for losses

MA_COLORS = {
    "ma5":  "#FF6D00",  # vivid orange
    "ma10": "#AA00FF",  # vivid purple
    "ma20": "#00BCD4",  # cyan
}

# PDF colours
C_TEXT    = colors.HexColor("#212121")
C_MUTED   = colors.HexColor("#616161")
C_ACCENT  = colors.HexColor("#1565C0")
C_ACCENT2 = colors.HexColor("#0D47A1")
C_GREEN   = colors.HexColor("#1B5E20")
C_RED     = colors.HexColor("#B71C1C")
C_HEAD    = colors.HexColor("#BBDEFB")    # light blue header
C_PANEL   = colors.HexColor("#F5F5F5")
C_PANEL2  = colors.HexColor("#E3F2FD")
C_BORDER  = colors.HexColor("#BDBDBD")
C_KPI_BG  = colors.HexColor("#0D47A1")
C_KPI_VAL = colors.HexColor("#82B1FF")
C_KPI_LBL = colors.HexColor("#BBDEFB")
C_WHITE   = colors.white

# Apply global matplotlib style
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
    "xtick.labelsize":   9,
    "ytick.labelsize":   9,
    "grid.color":        GRID_C,
    "grid.linewidth":    0.6,
    "legend.facecolor":  BG,
    "legend.edgecolor":  BORDER,
    "legend.fontsize":   9,
    "font.family":       "DejaVu Sans",
    "font.size":         10,
})

FOOTER_TXT = "Source: merolagani.com  ·  NEPSE ETL Pipeline  ·  For informational purposes only"

# PDF page geometry
_LM    = 2.0 * cm
_RM    = 2.0 * cm
_TM    = 2.0 * cm
_BM    = 2.0 * cm
PAGE_W = A4[0] - _LM - _RM   # ≈ 17.1 cm usable width


# ══════════════════════════════════════════════════════════════════════════════
# CHART HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_npr(ax):
    """Format y-axis as 'Rs 1,234'."""
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"Rs {x:,.0f}"))


def _shade(ax, x, y, color):
    """Subtle gradient fill under a line."""
    ax.fill_between(x, y, float(y.min()) * 0.999, alpha=0.12, color=color, linewidth=0)


def _trend_badge(ax, y_vals):
    """Show a ↑/↓ badge in the top-right corner of a price chart."""
    if len(y_vals) < 2:
        return
    first, last = float(y_vals.iloc[0]), float(y_vals.iloc[-1])
    pct = (last - first) / first * 100 if first > 0 else 0
    if abs(pct) < 0.3:
        txt, c = "→  Flat", MUTED
    elif pct > 0:
        txt, c = f"↑  +{pct:.2f}%", UP_C
    else:
        txt, c = f"↓  {pct:.2f}%", DOWN_C
    ax.text(0.985, 0.97, txt, transform=ax.transAxes, ha="right", va="top",
            fontsize=9, color=c, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor=BG, edgecolor=c, linewidth=1.2))


def _mark_hl(ax, x, y):
    """Annotate the session high and low on a price chart."""
    if len(y) < 3:
        return
    ih, il = y.idxmax(), y.idxmin()
    for idx, label, color, yoff in [(ih, f"H  Rs {y[ih]:,.0f}", UP_C, 14),
                                     (il, f"L  Rs {y[il]:,.0f}", DOWN_C, -18)]:
        ax.annotate(label, xy=(x[idx], y[idx]), xytext=(0, yoff),
                    textcoords="offset points", ha="center",
                    fontsize=8, color=color, fontweight="bold",
                    arrowprops=dict(arrowstyle="-", color=color, lw=0.8))


def _plot_ma_overlays(ax, sub: pd.DataFrame) -> list:
    """Draw MA5, MA10, MA20 overlays. Returns legend handles."""
    handles = []
    for col, label, lw, ls in [
        ("ma5",  "MA 5",  1.6, "--"),
        ("ma10", "MA 10", 1.6, "-."),
        ("ma20", "MA 20", 1.8, ":"),
    ]:
        valid = sub[["fetched_at", col]].dropna() if col in sub.columns else pd.DataFrame()
        if len(valid) >= 2:
            line, = ax.plot(valid["fetched_at"], valid[col],
                            color=MA_COLORS[col], linewidth=lw, linestyle=ls,
                            alpha=0.9, zorder=2, label=label)
            handles.append(line)
    return handles


def _save(fig, path: Path, pad=0.15) -> Path:
    """Save figure with consistent settings and close it."""
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=pad, facecolor=BG)
    plt.close(fig)
    log.info(f"Saved chart: {path.name}")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL CHARTS
# ══════════════════════════════════════════════════════════════════════════════

def _chart_individual_line(sym: str, sub: pd.DataFrame, graphs_dir: Path) -> Path:
    """Price + volume chart for a single symbol."""
    color = PALETTE[hash(sym) % len(PALETTE)]

    # Extra tall figure so title / subtitle / price / volume don't overlap
    fig, (ax_p, ax_v) = plt.subplots(
        2, 1, figsize=(12, 7.5),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.35},
        sharex=True,
    )
    fig.patch.set_facecolor(BG)

    # ── Price panel ────────────────────────────────────────────────────────
    price_line, = ax_p.plot(sub["fetched_at"], sub["close"],
                            color=color, linewidth=2.5,
                            solid_capstyle="round", zorder=3, label="Close")
    _shade(ax_p, sub["fetched_at"], sub["close"], color)
    ax_p.scatter([sub["fetched_at"].iloc[-1]], [sub["close"].iloc[-1]],
                 color=color, s=55, zorder=4, edgecolors=BG, linewidth=2)

    _mark_hl(ax_p, sub["fetched_at"].reset_index(drop=True), sub["close"].reset_index(drop=True))
    _trend_badge(ax_p, sub["close"])
    ma_handles = _plot_ma_overlays(ax_p, sub)

    if ma_handles:
        ax_p.legend(handles=[price_line] + ma_handles,
                    loc="upper left", framealpha=0.9, fontsize=8.5,
                    borderpad=0.6, handlelength=2)

    close_last = sub["close"].iloc[-1]
    pct_last   = float(sub["pct_change_calc"].iloc[-1]) if "pct_change_calc" in sub.columns else 0.0
    sign       = "+" if pct_last >= 0 else ""

    # Title above price panel — enough vertical room now
    ax_p.set_title(f"{sym}  ·  Close Price — Intraday Session",
                   fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)

    # One-line stats subtitle (no overlap because hspace=0.35)
    ax_p.set_xlabel("")
    stats = (f"Close Rs {close_last:,.2f}  |  Change {sign}{pct_last:.2f}%  |  "
             f"High Rs {sub['high'].max():,.2f}  |  Low Rs {sub['low'].min():,.2f}  |  "
             f"Vol {int(sub['volume'].iloc[-1]):,}")
    ax_p.text(0.0, -0.04, stats, transform=ax_p.transAxes,
              fontsize=8, color=MUTED, va="top")

    _fmt_npr(ax_p)
    ax_p.set_ylabel("Price (NPR)", fontsize=9, color=MUTED, labelpad=6)
    ax_p.grid(True, axis="y", linestyle="--", alpha=0.7)

    # ── Volume panel ───────────────────────────────────────────────────────
    pct_vals = sub.get("pct_change_calc", pd.Series([0] * len(sub)))
    v_colors = [UP_C if v >= 0 else DOWN_C for v in pct_vals]
    ax_v.bar(sub["fetched_at"], sub["volume"], color=v_colors, alpha=0.75, width=0.004)
    ax_v.set_ylabel("Volume", fontsize=8, color=MUTED, labelpad=6)
    ax_v.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}K"))
    ax_v.grid(True, axis="y", linestyle="--", alpha=0.7)
    ax_v.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_v.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(ax_v.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    ax_v.set_xlabel("Time (NPT)", fontsize=9, color=MUTED, labelpad=6)

    fig.text(0.5, 0.01, FOOTER_TXT, ha="center", fontsize=7, color=MUTED)
    fig.subplots_adjust(bottom=0.12, top=0.93)

    return _save(fig, graphs_dir / f"line_{sym}.png")


def _chart_overlay(df: pd.DataFrame, graphs_dir: Path) -> Path:
    """Normalised close price overlay — all symbols on one chart."""
    symbols = [s for s in df["symbol"].unique() if s != "NEPSE"][:9]
    fig, ax = plt.subplots(figsize=(13, 6))

    for i, sym in enumerate(symbols):
        sub = df[df["symbol"] == sym].sort_values("fetched_at")
        if sub.empty:
            continue
        # Normalise to 100 at session start so all lines start at same point
        base = sub["close"].iloc[0]
        norm = sub["close"] / base * 100
        ax.plot(sub["fetched_at"], norm, label=sym,
                color=PALETTE[i % len(PALETTE)], linewidth=2,
                marker="o", markersize=3, solid_capstyle="round")

    ax.axhline(100, color=BORDER, linewidth=1, linestyle="--", zorder=0)
    ax.set_title("Close Price Overlay  ·  All Symbols (Indexed to 100)",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.set_xlabel("Time (NPT)", fontsize=9, color=MUTED)
    ax.set_ylabel("Indexed Price (Base = 100)", fontsize=9, color=MUTED)
    ax.legend(ncol=3, framealpha=0.9, fontsize=9)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.subplots_adjust(bottom=0.15, top=0.92)
    return _save(fig, graphs_dir / "overlay_close_lines.png")


def _chart_pct_bars(df: pd.DataFrame, graphs_dir: Path) -> Path:
    """Horizontal bar chart of latest % change per symbol."""
    latest = (df.sort_values("fetched_at").groupby("symbol").last()
                .reset_index().sort_values("pct_change_calc"))
    bar_colors = [UP_C if v >= 0 else DOWN_C for v in latest["pct_change_calc"]]

    fig, ax = plt.subplots(figsize=(12, max(5, len(latest) * 0.55 + 1.5)))
    bars = ax.barh(latest["symbol"], latest["pct_change_calc"],
                   color=bar_colors, edgecolor="white", linewidth=0.5,
                   height=0.6, alpha=0.9)

    # Labels outside the bar
    max_abs = latest["pct_change_calc"].abs().max()
    offset  = max_abs * 0.025
    for bar, val in zip(bars, latest["pct_change_calc"]):
        sign = "+" if val >= 0 else ""
        ax.text(val + (offset if val >= 0 else -offset),
                bar.get_y() + bar.get_height() / 2,
                f"{sign}{val:.2f}%", va="center",
                ha="left" if val >= 0 else "right",
                fontsize=9, color=TEXT, fontweight="bold")

    ax.axvline(0, color=TEXT, linewidth=1.2)
    ax.set_title("Latest % Change vs Previous Close",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.set_xlabel("% Change", fontsize=9, color=MUTED)
    ax.grid(True, axis="x", linestyle="--", alpha=0.7)
    n_up = (latest["pct_change_calc"] > 0).sum()
    n_dn = (latest["pct_change_calc"] < 0).sum()
    ax.text(0.99, 0.02, f"▲ {n_up} gainers  ·  ▼ {n_dn} losers",
            transform=ax.transAxes, ha="right", va="bottom",
            fontsize=9, color=MUTED,
            bbox=dict(boxstyle="round,pad=0.35", facecolor=BG, edgecolor=BORDER))
    fig.subplots_adjust(left=0.12, right=0.92, bottom=0.1, top=0.92)
    return _save(fig, graphs_dir / "pct_change_bars.png")


def _chart_candlestick(df: pd.DataFrame, graphs_dir: Path) -> Path:
    """2×2 candlestick grid for the top 4 symbols by row count."""
    top_syms = df.groupby("symbol")["symbol"].count().nlargest(4).index.tolist()

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle("Candlestick Charts  ·  Top 4 Symbols",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    axes = axes.flatten()

    for ai, sym in enumerate(top_syms):
        ax  = axes[ai]
        sub = df[df["symbol"] == sym].sort_values("fetched_at").reset_index(drop=True)
        if len(sub) < 2:
            ax.text(0.5, 0.5, f"{sym}\nNo data", transform=ax.transAxes,
                    ha="center", va="center", color=MUTED, fontsize=11)
            continue

        for i, row in sub.iterrows():
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            clr = UP_C if c >= o else DOWN_C
            # Wick
            ax.plot([i, i], [l, h], color=clr, linewidth=1.2, zorder=2)
            # Body (min height 0.5 so tiny bodies are still visible)
            rect = Rectangle((i - 0.35, min(o, c)), 0.7, max(abs(c - o), 0.5),
                              facecolor=clr, edgecolor="white",
                              linewidth=0.5, alpha=0.9, zorder=3)
            ax.add_patch(rect)

        ax.set_xlim(-0.8, len(sub) - 0.2)
        lo, hi = sub["low"].min(), sub["high"].max()
        margin = (hi - lo) * 0.08
        ax.set_ylim(lo - margin, hi + margin)

        # X-axis time labels — spread out to avoid overlap
        n    = len(sub)
        step = max(1, n // 6)
        tidx = list(range(0, n, step))
        ax.set_xticks(tidx)
        ax.set_xticklabels(
            [sub["fetched_at"].iloc[j].strftime("%H:%M") for j in tidx],
            rotation=30, ha="right", fontsize=8
        )

        ax.set_title(sym, fontsize=12, fontweight="bold", color=TEXT, pad=8)
        ax.set_ylabel("NPR", fontsize=8, color=MUTED, labelpad=4)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.grid(True, axis="y", linestyle="--", alpha=0.6)

    for j in range(len(top_syms), 4):
        axes[j].set_visible(False)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return _save(fig, graphs_dir / "candlestick.png")


def _chart_volume(df: pd.DataFrame, graphs_dir: Path) -> Path:
    """Total session volume by symbol — horizontal bars."""
    top = df.groupby("symbol")["volume"].sum().nlargest(8).sort_values()
    fig, ax = plt.subplots(figsize=(12, max(5, len(top) * 0.6 + 1.5)))
    bars = ax.barh(top.index, top.values,
                   color=[PALETTE[i % len(PALETTE)] for i in range(len(top))],
                   edgecolor="white", linewidth=0.5, height=0.6, alpha=0.9)
    max_v = top.max()
    for bar, val in zip(bars, top.values):
        ax.text(val + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,}", va="center", fontsize=9, color=MUTED, fontweight="bold")
    ax.set_title("Total Session Volume  ·  Top Symbols",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.set_xlabel("Shares Traded", fontsize=9, color=MUTED)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.grid(True, axis="x", linestyle="--", alpha=0.7)
    fig.subplots_adjust(left=0.12, right=0.92, bottom=0.1, top=0.92)
    return _save(fig, graphs_dir / "volume_bars.png")


def _chart_correlation(df: pd.DataFrame, graphs_dir: Path) -> Path | None:
    """Correlation heatmap of % changes across all symbols."""
    pivot = (df.pivot_table(index="fetched_at", columns="symbol",
                            values="pct_change_calc", aggfunc="last")
               .dropna(axis=1, thresh=2))
    if pivot.shape[1] < 2:
        return None
    corr = pivot.corr()

    fig, ax = plt.subplots(figsize=(max(8, len(corr) * 0.9), max(7, len(corr) * 0.8)))
    mask = np.triu(np.ones_like(corr, dtype=bool))
    sns.heatmap(
        corr, mask=mask,
        cmap="RdYlGn",           # red–yellow–green: much more readable than mono-blue
        center=0, vmin=-1, vmax=1,
        annot=True, fmt=".2f", annot_kws={"size": 9, "weight": "bold"},
        linewidths=0.8, linecolor=BORDER, ax=ax,
        cbar_kws={"shrink": 0.8, "label": "Correlation"},
    )
    ax.set_title("% Change Correlation  ·  All Symbols",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.tick_params(axis="x", rotation=45, labelsize=9)
    ax.tick_params(axis="y", rotation=0,  labelsize=9)
    fig.subplots_adjust(bottom=0.18, top=0.92)
    return _save(fig, graphs_dir / "correlation_heatmap.png")


def _chart_cum_return(df: pd.DataFrame, graphs_dir: Path) -> Path:
    """Cumulative % return over session for each non-NEPSE symbol."""
    symbols = [s for s in df["symbol"].unique() if s != "NEPSE"][:8]
    fig, ax = plt.subplots(figsize=(13, 6))
    for i, sym in enumerate(symbols):
        sub = df[df["symbol"] == sym].sort_values("fetched_at")
        if sub.empty:
            continue
        ax.plot(sub["fetched_at"], sub["cum_return_pct"],
                label=sym, color=PALETTE[i % len(PALETTE)],
                linewidth=2.2, solid_capstyle="round")
    ax.axhline(0, color=MUTED, linewidth=1.2, linestyle="--", zorder=0)
    ax.set_title("Cumulative Return (%)  ·  Session",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.set_xlabel("Time (NPT)", fontsize=9, color=MUTED)
    ax.set_ylabel("Cumulative %", fontsize=9, color=MUTED)
    ax.legend(ncol=3, framealpha=0.9, fontsize=9)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.subplots_adjust(bottom=0.15, top=0.92)
    return _save(fig, graphs_dir / "cumulative_return.png")


def _chart_summary_table(df: pd.DataFrame, graphs_dir: Path) -> Path:
    """Colour-coded OHLCV summary table image."""
    latest = (df.sort_values("fetched_at").groupby("symbol").last()
                .reset_index()[["symbol","open","high","low","close","volume","pct_change_calc"]]
                .sort_values("pct_change_calc", ascending=False))
    latest.columns = ["Symbol","Open","High","Low","Close","Volume","Chg%"]
    for c in ("Open","High","Low","Close"):
        latest[c] = latest[c].map(lambda x: f"Rs {x:,.2f}")
    latest["Volume"] = latest["Volume"].map(lambda x: f"{x:,}")
    latest["Chg%"]   = latest["Chg%"].map(lambda x: f"{'+'if x>=0 else ''}{x:.2f}%")

    n_rows = len(latest)
    fig, ax = plt.subplots(figsize=(14, max(4, n_rows * 0.52 + 1.8)))
    ax.axis("off")
    tbl = ax.table(cellText=latest.values, colLabels=latest.columns,
                   cellLoc="center", loc="center", bbox=[0, 0, 1, 1])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    for (r, c_idx), cell in tbl.get_celld().items():
        cell.set_edgecolor(BORDER)
        cell.set_linewidth(0.5)
        if r == 0:
            cell.set_facecolor("#BBDEFB")
            cell.set_text_props(color=TEXT, fontweight="bold", fontsize=10)
        else:
            cell.set_facecolor("#FFFFFF" if r % 2 == 0 else "#F5F5F5")
            cell.set_text_props(color=TEXT, fontsize=9)
        if c_idx == 6 and r > 0:
            val = latest.iloc[r - 1]["Chg%"]
            cell.set_facecolor("#E8F5E9" if "+" in val else "#FFEBEE")
            cell.set_text_props(color=UP_C if "+" in val else DOWN_C,
                                fontweight="bold")
    ax.set_title("NEPSE  ·  Session Summary  ·  Latest OHLCV",
                 fontsize=13, fontweight="bold", color=TEXT, pad=14)
    return _save(fig, graphs_dir / "summary_table.png")


def _chart_nepse_index(df: pd.DataFrame, graphs_dir: Path) -> Path | None:
    """NEPSE index line + volume chart."""
    nepse = df[df["symbol"] == "NEPSE"].sort_values("fetched_at")
    if nepse.empty:
        return None
    color = PALETTE[0]

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(13, 8.5),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.35},
        sharex=True,
    )
    ax1.plot(nepse["fetched_at"], nepse["close"],
             color=color, linewidth=2.5, solid_capstyle="round", zorder=3)
    _shade(ax1, nepse["fetched_at"], nepse["close"], color)
    _mark_hl(ax1, nepse["fetched_at"].reset_index(drop=True),
             nepse["close"].reset_index(drop=True))
    _trend_badge(ax1, nepse["close"])
    _plot_ma_overlays(ax1, nepse)

    ax1.set_title("NEPSE Index  ·  Intraday Session",
                  fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax1.set_ylabel("Index Value", fontsize=9, color=MUTED, labelpad=6)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax1.grid(True, linestyle="--", alpha=0.7)

    v_colors = [UP_C if v >= 0 else DOWN_C for v in nepse["pct_change_calc"]]
    ax2.bar(nepse["fetched_at"], nepse["volume"], color=v_colors, alpha=0.8, width=0.003)
    ax2.set_ylabel("Volume", fontsize=8, color=MUTED, labelpad=6)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}K"))
    ax2.set_xlabel("Time (NPT)", fontsize=9, color=MUTED, labelpad=6)
    ax2.grid(True, linestyle="--", alpha=0.7)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.subplots_adjust(bottom=0.12, top=0.93)
    return _save(fig, graphs_dir / "nepse_index.png")


# ══════════════════════════════════════════════════════════════════════════════
# MASTER CHART GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def generate_all_charts(df: pd.DataFrame,
                        date_str: str | None = None) -> dict[str, Path]:
    """
    Generate all charts and return a dict mapping name → file path.
    Individual symbol charts are keyed as 'line_SYMBOL'.
    """
    graphs_dir, _ = get_session_dirs(date_str)
    charts: dict[str, Path] = {}

    # Per-symbol charts
    for i, sym in enumerate(df["symbol"].unique()):
        sub = df[df["symbol"] == sym].sort_values("fetched_at").reset_index(drop=True)
        if len(sub) < 2:
            continue
        try:
            charts[f"line_{sym}"] = _chart_individual_line(sym, sub, graphs_dir)
        except Exception as e:
            log.error(f"Individual chart failed for {sym}: {e}", exc_info=True)

    # Summary charts
    for key, fn in [
        ("overlay",     _chart_overlay),
        ("pct_bars",    _chart_pct_bars),
        ("candlestick", _chart_candlestick),
        ("volume",      _chart_volume),
        ("correlation", _chart_correlation),
        ("cum_return",  _chart_cum_return),
        ("summary",     _chart_summary_table),
        ("nepse_index", _chart_nepse_index),
    ]:
        try:
            p = fn(df, graphs_dir)
            if p:
                charts[key] = p
        except Exception as e:
            log.error(f"Chart '{key}' failed: {e}", exc_info=True)

    log.info(f"Generated {len(charts)} chart(s) in {graphs_dir}")
    return charts


# ══════════════════════════════════════════════════════════════════════════════
# PDF HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "Cover": ParagraphStyle(
            "Cover", parent=base["Normal"],
            fontSize=40, fontName="Helvetica-Bold",
            textColor=C_ACCENT, alignment=TA_CENTER, leading=48, spaceAfter=8,
        ),
        "CoverSub": ParagraphStyle(
            "CoverSub", parent=base["Normal"],
            fontSize=13, fontName="Helvetica",
            textColor=C_MUTED, alignment=TA_CENTER, leading=20, spaceAfter=4,
        ),
        "Banner": ParagraphStyle(
            "Banner", parent=base["Normal"],
            fontSize=11, fontName="Helvetica-Bold",
            textColor=C_WHITE, leading=16, leftIndent=8,
        ),
        "Sub": ParagraphStyle(
            "Sub", parent=base["Normal"],
            fontSize=11, fontName="Helvetica-Bold",
            textColor=C_ACCENT, leading=16, spaceBefore=4, spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "Body", parent=base["Normal"],
            fontSize=9.5, fontName="Helvetica",
            textColor=C_TEXT, leading=15, spaceAfter=4,
        ),
        "Interp": ParagraphStyle(
            "Interp", parent=base["Normal"],
            fontSize=8.5, fontName="Helvetica-Oblique",
            textColor=C_MUTED, leading=13, leftIndent=10, spaceAfter=4,
        ),
        "Small": ParagraphStyle(
            "Small", parent=base["Normal"],
            fontSize=7.5, fontName="Helvetica",
            textColor=C_MUTED, leading=11, alignment=TA_CENTER,
        ),
        "Footer": ParagraphStyle(
            "Footer", parent=base["Normal"],
            fontSize=7.5, fontName="Helvetica",
            textColor=C_MUTED, alignment=TA_CENTER, leading=11,
        ),
        "KPIVal": ParagraphStyle(
            "KPIVal", parent=base["Normal"],
            fontSize=22, fontName="Helvetica-Bold",
            textColor=C_KPI_VAL, alignment=TA_CENTER, leading=28,
        ),
        "KPILbl": ParagraphStyle(
            "KPILbl", parent=base["Normal"],
            fontSize=8, fontName="Helvetica",
            textColor=C_KPI_LBL, alignment=TA_CENTER, leading=11,
        ),
    }


def _sp(pts: int = 12) -> Spacer:
    return Spacer(1, pts)


def _hr(c=C_BORDER, thick=0.5) -> HRFlowable:
    return HRFlowable(width="100%", thickness=thick, color=c,
                      spaceBefore=4, spaceAfter=4)


def _banner(text: str, styles: dict) -> list:
    """Dark blue section header banner."""
    tbl = Table([[Paragraph(text, styles["Banner"])]], colWidths=[PAGE_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_ACCENT2),
        ("TOPPADDING",    (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
    ]))
    return [_sp(10), tbl, _sp(8)]


def _img_block(path: Path, caption: str, styles: dict,
               max_h: float = 9.5 * cm) -> list:
    """Embed a chart PNG into the PDF, scaled to fit, with caption."""
    if not path or not path.exists():
        return [_sp(6), Paragraph(f"[Chart unavailable: {caption}]", styles["Small"]), _sp(6)]
    img   = Image(str(path))
    scale = min(PAGE_W / img.imageWidth, max_h / img.imageHeight, 1.0)
    img.drawWidth  = img.imageWidth  * scale
    img.drawHeight = img.imageHeight * scale
    return [_sp(6), img, _sp(4), Paragraph(f"<i>{caption}</i>", styles["Small"]), _sp(16)]


def _kpi_cards(metrics: list[tuple[str, str]], styles: dict) -> Table:
    n   = len(metrics)
    cw  = [PAGE_W / n] * n
    tbl = Table(
        [[Paragraph(v, styles["KPIVal"]) for v, _ in metrics],
         [Paragraph(l, styles["KPILbl"]) for _, l in metrics]],
        colWidths=cw,
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_KPI_BG),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.4, colors.HexColor("#1e3a5f")),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
    ]))
    return tbl


def _stat_strip(items: list[tuple[str, str, bool]], styles: dict) -> Table:
    """One-row stats table with coloured change cells."""
    hdrs = [Paragraph(f"<b>{h}</b>", styles["Small"]) for h, _, _ in items]
    vals = []
    for _, val, is_chg in items:
        if is_chg:
            col = C_GREEN if ("▲" in val or ("+" in val and "▼" not in val)) else C_RED
            p   = Paragraph(f"<b>{val}</b>",
                            ParagraphStyle("_c", parent=styles["Small"],
                                           textColor=col, fontName="Helvetica-Bold",
                                           alignment=TA_CENTER))
        else:
            p = Paragraph(val, styles["Small"])
        vals.append(p)
    cw  = [PAGE_W / len(items)] * len(items)
    tbl = Table([hdrs, vals], colWidths=cw)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  C_HEAD),
        ("BACKGROUND",    (0, 1), (-1, 1),  C_PANEL),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, C_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
    ]))
    return tbl


def _df_table(df_slice: pd.DataFrame, styles: dict) -> Table:
    """DataFrame → ReportLab Table with zebra striping."""
    header = [Paragraph(f"<b>{c}</b>", styles["Small"]) for c in df_slice.columns]
    rows   = [header]
    for _, row in df_slice.iterrows():
        rows.append([Paragraph(str(v), styles["Small"]) for v in row])
    cw  = [PAGE_W / len(df_slice.columns)] * len(df_slice.columns)
    tbl = Table(rows, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  C_HEAD),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  C_TEXT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_PANEL2]),
        ("TEXTCOLOR",      (0, 1), (-1, -1), C_TEXT),
        ("BOX",            (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",      (0, 0), (-1, -1), 0.3, C_BORDER),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("LEFTPADDING",    (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 5),
        ("ALIGN",          (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE",       (0, 0), (-1, -1), 7.5),
    ]))
    return tbl


# ══════════════════════════════════════════════════════════════════════════════
# PDF BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def generate_report(
    charts:           dict[str, Path],
    df:               pd.DataFrame,
    date_str:         str | None = None,
    out_name:         str | None = None,
    email_recipients: list[str] | None = None,
    email_cc:         list[str] | None = None,
) -> Path:
    """
    Assemble the PDF report from charts and data, then notify + email.

    Returns the path to the generated PDF.
    """
    _, session_dir = get_session_dirs(date_str)
    out_name = out_name or f"NEPSE_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    out_path = session_dir / out_name

    styles = _styles()
    doc    = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=_LM, rightMargin=_RM,
        topMargin=_TM,  bottomMargin=_BM,
        title="NEPSE ETL Report", author="NEPSE ETL Pipeline",
    )
    story  = []
    now_dt = datetime.now()

    # ── Cover page ────────────────────────────────────────────────────────────
    story.append(_sp(3 * cm))
    story.append(Paragraph("NEPSE", styles["Cover"]))
    story.append(_sp(6))
    story.append(Paragraph("Live ETL  ·  Analytics Report", styles["CoverSub"]))
    story.append(_sp(4))
    story.append(Paragraph(now_dt.strftime("%A, %d %B %Y  |  %H:%M NPT"), styles["CoverSub"]))

    summary_dict: dict = {}
    if not df.empty:
        mn = df["fetched_at"].min().strftime("%d %b  %H:%M")
        mx = df["fetched_at"].max().strftime("%d %b  %H:%M")
        story.append(_sp(4))
        story.append(Paragraph(f"Session window: {mn} – {mx} NPT", styles["CoverSub"]))

        lat    = df.sort_values("fetched_at").groupby("symbol").last()
        t_vol  = int(lat["volume"].sum())
        avg_ch = float(lat["pct_change_calc"].mean())
        n_up   = int((lat["pct_change_calc"] > 0).sum())
        n_dn   = int((lat["pct_change_calc"] < 0).sum())
        n_sym  = df["symbol"].nunique()

        summary_dict = {"n_symbols": n_sym, "total_volume": t_vol,
                        "gainers": n_up, "losers": n_dn, "avg_change": avg_ch}

        story.append(_sp(28))
        story.append(_hr(C_ACCENT, thick=2))
        story.append(_sp(20))
        story.append(_kpi_cards([
            (f"{n_sym}",          "Symbols Tracked"),
            (f"{t_vol:,}",        "Total Volume"),
            (f"{n_up} / {n_dn}", "Gainers / Losers"),
            (f"{avg_ch:+.2f}%",  "Avg % Change"),
        ], styles))

    story.append(_sp(28))
    story.append(_hr(C_BORDER))
    story.append(_sp(8))
    story.append(Paragraph(
        "Generated by NEPSE ETL Pipeline  ·  Data source: merolagani.com  ·  "
        "For informational use only.",
        styles["Footer"],
    ))
    story.append(PageBreak())

    # ── Section 1: Individual company charts ──────────────────────────────────
    story += _banner("1.  Individual Company Price Charts", styles)
    story.append(Paragraph(
        "Intraday close price with volume bars. Moving averages (MA 5 / 10 / 20) "
        "are overlaid in vivid orange, purple, and cyan respectively. "
        "The trend badge and H/L annotations are shown on each chart.",
        styles["Body"],
    ))
    story.append(_sp(10))

    sym_keys = sorted(k for k in charts if k.startswith("line_"))
    for idx, key in enumerate(sym_keys):
        sym  = key.replace("line_", "")
        sub  = df[df["symbol"] == sym].sort_values("fetched_at")

        # Per-symbol header block
        header_block: list = []
        if not sub.empty and len(sub) >= 2:
            first_c = float(sub["close"].iloc[0])
            last_c  = float(sub["close"].iloc[-1])
            pct     = (last_c - first_c) / first_c * 100 if first_c > 0 else 0
            hi      = float(sub["high"].max())
            lo      = float(sub["low"].min())
            vol     = int(sub["volume"].iloc[-1])
            sign    = "▲" if pct >= 0 else "▼"

            def last_ma(col):
                return sub[col].dropna().iloc[-1] if col in sub.columns and not sub[col].dropna().empty else None

            ma_parts = [f"MA5 Rs {v:,.2f}" for col, v in [("ma5", last_ma("ma5"))] if v] + \
                       [f"MA10 Rs {v:,.2f}" for col, v in [("ma10", last_ma("ma10"))] if v] + \
                       [f"MA20 Rs {v:,.2f}" for col, v in [("ma20", last_ma("ma20"))] if v]
            ma_str = "  |  ".join(ma_parts)

            note = (
                f"{sym} {'gained' if pct >= 0 else 'lost'} {abs(pct):.2f}% this session, "
                f"trading between Rs {lo:,.2f} and Rs {hi:,.2f}. "
                f"Last close: Rs {last_c:,.2f}  |  Volume: {vol:,}."
                + (f"  Moving averages — {ma_str}." if ma_str else "")
            )
            header_block = [
                Paragraph(f"1.{idx+1}  {sym}", styles["Sub"]),
                _sp(4),
                _stat_strip([
                    ("Open",   f"Rs {first_c:,.2f}", False),
                    ("High",   f"Rs {hi:,.2f}",      False),
                    ("Low",    f"Rs {lo:,.2f}",       False),
                    ("Close",  f"Rs {last_c:,.2f}",  False),
                    ("Change", f"{sign} {abs(pct):.2f}%", True),
                    ("Volume", f"{vol:,}",            False),
                ], styles),
                _sp(4),
                Paragraph(note, styles["Interp"]),
            ]
        else:
            header_block = [Paragraph(f"1.{idx+1}  {sym}", styles["Sub"])]

        img_block = _img_block(
            charts[key],
            f"Figure 1.{idx+1}  —  {sym}  Close Price, Moving Averages & Volume",
            styles, max_h=9.5 * cm,
        )
        story.append(KeepTogether(header_block + img_block))

        # Page break every 2 symbols to keep layout clean
        if (idx + 1) % 2 == 0 and idx < len(sym_keys) - 1:
            story.append(PageBreak())
        else:
            story.append(_sp(10))

    story.append(PageBreak())

    # ── Section 2: NEPSE Index ────────────────────────────────────────────────
    story += _banner("2.  NEPSE Index  ·  Intraday Overview", styles)
    story.append(Paragraph(
        "The NEPSE index gives a macro view of the overall market session. "
        "Rising index with increasing green volume bars confirms broad buying pressure.",
        styles["Body"],
    ))
    if "nepse_index" in charts:
        story += _img_block(charts["nepse_index"],
                            "Figure 2  —  NEPSE Index: Close, MAs & Volume",
                            styles, max_h=11.0 * cm)
    story.append(PageBreak())

    # ── Section 3: Overlay ────────────────────────────────────────────────────
    story += _banner("3.  Close Price Overlay  ·  All Symbols", styles)
    story.append(Paragraph(
        "Prices are indexed to 100 at session open so all symbols are directly comparable "
        "regardless of their absolute price level. Deviations signal stock-specific news.",
        styles["Body"],
    ))
    if "overlay" in charts:
        story += _img_block(charts["overlay"],
                            "Figure 3  —  Close Price Overlay (Indexed to 100)",
                            styles, max_h=9.0 * cm)
    story.append(PageBreak())

    # ── Section 4: Returns ────────────────────────────────────────────────────
    story += _banner("4.  Returns & Cumulative Performance", styles)
    story.append(Paragraph(
        "The % change bar shows each symbol's return vs its previous close. "
        "The cumulative chart tracks compounding returns over the full session.",
        styles["Body"],
    ))
    story.append(_sp(6))
    if "pct_bars"   in charts:
        story += _img_block(charts["pct_bars"],   "Figure 4  —  Latest % Change vs Previous Close", styles)
    if "cum_return" in charts:
        story += _img_block(charts["cum_return"], "Figure 5  —  Cumulative Return (%) Over Session", styles)
    story.append(PageBreak())

    # ── Section 5: Candlestick ────────────────────────────────────────────────
    story += _banner("5.  Candlestick Analysis  ·  Top Symbols", styles)
    story.append(Paragraph(
        "Green candles = close ≥ open (bullish). Red candles = close < open (bearish). "
        "Long wicks indicate price rejection at those levels.",
        styles["Body"],
    ))
    if "candlestick" in charts:
        story += _img_block(charts["candlestick"],
                            "Figure 6  —  Candlestick Charts: Top 4 Symbols",
                            styles, max_h=13.0 * cm)
    story.append(PageBreak())

    # ── Section 6: Volume & Correlation ──────────────────────────────────────
    story += _banner("6.  Volume & Correlation", styles)
    story.append(Paragraph(
        "High volume on a rising stock confirms demand. "
        "The correlation heatmap uses a red–yellow–green scale: "
        "+1 (dark green) = perfectly co-moving, 0 (yellow) = independent, "
        "-1 (dark red) = opposite movement.",
        styles["Body"],
    ))
    story.append(_sp(6))
    if "volume"      in charts:
        story += _img_block(charts["volume"],      "Figure 7  —  Total Session Volume by Symbol", styles)
    if "correlation" in charts:
        story += _img_block(charts["correlation"], "Figure 8  —  % Change Correlation Heatmap",   styles)
    story.append(PageBreak())

    # ── Section 7: Summary table ──────────────────────────────────────────────
    story += _banner("7.  Session Summary Table", styles)
    story.append(Paragraph(
        "Latest OHLCV snapshot for all tracked symbols, sorted by % change descending. "
        "Green cells = positive return, red cells = negative return.",
        styles["Body"],
    ))
    if "summary" in charts:
        story += _img_block(charts["summary"], "Figure 9  —  OHLCV Summary (Latest Values)",
                            styles, max_h=11.0 * cm)
    story.append(PageBreak())

    # ── Section 8: Statistics ─────────────────────────────────────────────────
    story += _banner("8.  Descriptive Statistics", styles)
    story.append(Paragraph(
        "Count, mean, std, min, quartiles, and max for all numeric columns "
        "across every polling snapshot in this session.",
        styles["Body"],
    ))
    story.append(_sp(8))
    if not df.empty:
        cols  = [c for c in ["open","high","low","close","volume","pct_change_calc",
                              "range","ma5","ma10","ma20"] if c in df.columns]
        desc  = df[cols].describe().round(2).reset_index()
        desc.columns = ["Stat"] + cols
        story.append(_df_table(desc, styles))
    story.append(PageBreak())

    # ── Section 9: Data sample ────────────────────────────────────────────────
    story += _banner("9.  Cleaned Data Sample  ·  Latest 20 Rows", styles)
    story.append(Paragraph(
        "The 20 most recently fetched rows from this session.",
        styles["Body"],
    ))
    story.append(_sp(8))
    if not df.empty:
        ma_cols = [c for c in ["ma5","ma10","ma20"] if c in df.columns]
        show    = [c for c in ["fetched_at","symbol","open","high","low","close",
                               "volume","pct_change_calc","direction"] + ma_cols
                   if c in df.columns]
        samp = df.sort_values("fetched_at", ascending=False).head(20)[show].copy()
        samp["fetched_at"] = samp["fetched_at"].dt.strftime("%H:%M:%S")
        for c in ["open","high","low","close"] + ma_cols:
            if c in samp:
                samp[c] = samp[c].map(lambda x: f"{float(x):,.2f}" if pd.notna(x) else "—")
        if "volume" in samp:
            samp["volume"] = samp["volume"].map(lambda x: f"{int(x):,}")
        if "pct_change_calc" in samp:
            samp["pct_change_calc"] = samp["pct_change_calc"].map(
                lambda x: f"{'+'if float(x)>=0 else ''}{float(x):.2f}%" if pd.notna(x) else "—"
            )
        samp.columns = [c.replace("_calc","").replace("_"," ").title() for c in samp.columns]
        story.append(_df_table(samp, styles))

    # ── Final footer ──────────────────────────────────────────────────────────
    story.append(_sp(28))
    story.append(_hr(C_BORDER))
    story.append(_sp(8))
    story.append(Paragraph(
        f"NEPSE ETL Pipeline  ·  Report generated "
        f"{now_dt.strftime('%d %b %Y  %H:%M:%S')} NPT  ·  "
        "Data source: merolagani.com  ·  For informational purposes only.",
        styles["Footer"],
    ))

    # ── Build PDF ──────────────────────────────────────────────────────────────
    doc.build(story)
    log.info(f"PDF report saved: {out_path}")

    # ── Desktop notification ───────────────────────────────────────────────────
    try:
        from notifier import notify_async
        notify_async("NEPSE Report Ready", f"PDF saved: {out_path.name}", pdf_path=out_path)
    except Exception as e:
        log.debug(f"Notification error (non-critical): {e}")

    # ── Email ──────────────────────────────────────────────────────────────────
    try:
        from email_sender import send_report
        ok = send_report(out_path, recipients=email_recipients,
                         cc=email_cc, summary=summary_dict or None)
        log.info("Report emailed." if ok else "Email not sent — check config.")
    except Exception as e:
        log.error(f"Email step error: {e}", exc_info=True)

    return out_path


# ══════════════════════════════════════════════════════════════════════════════
# CSV LOADER (was load_cleaned() in loader.py)
# ══════════════════════════════════════════════════════════════════════════════

def load_cleaned() -> pd.DataFrame:
    """Load cleaned.csv from disk."""
    if not CLEANED_CSV.exists():
        raise FileNotFoundError(f"cleaned.csv not found at {CLEANED_CSV}")
    df = pd.read_csv(CLEANED_CSV, parse_dates=["fetched_at", "date"])
    log.info(f"Loaded cleaned.csv: {len(df)} rows")
    return df


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df_     = load_cleaned()
    charts_ = generate_all_charts(df_)
    path_   = generate_report(charts_, df_)
    print(f"Report: {path_}")
