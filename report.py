"""
report.py  ─  Stage 3–5: Charts → PDF → Notify → Email
Generates all charts, assembles the PDF, fires notification and email.

Usage:
    python report.py        # from cleaned.csv
"""

import warnings; warnings.filterwarnings("ignore")
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib; matplotlib.use("Agg")
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

# ── Colour constants ───────────────────────────────────────────────────────────
PALETTE = ["#1565C0","#D84315","#2E7D32","#6A1B9A","#F57F17",
           "#00838F","#AD1457","#4E342E","#00695C","#283593"]
BG, PANEL, BORDER, TEXT, MUTED, GRID_C = "#FFF","#F5F5F5","#BDBDBD","#212121","#616161","#E0E0E0"
UP_C, DOWN_C = "#1B5E20", "#B71C1C"
MA_COLORS = {"ma5":"#FF6D00","ma10":"#AA00FF","ma20":"#00BCD4"}

C = {k: colors.HexColor(v) for k, v in {
    "text":"#212121","muted":"#616161","accent":"#1565C0","accent2":"#0D47A1",
    "green":"#1B5E20","red":"#B71C1C","head":"#BBDEFB","panel":"#F5F5F5",
    "panel2":"#E3F2FD","border":"#BDBDBD","kpi_bg":"#0D47A1",
    "kpi_val":"#82B1FF","kpi_lbl":"#BBDEFB","white":"#FFFFFF",
}.items()}

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": PANEL, "axes.edgecolor": BORDER,
    "axes.labelcolor": TEXT, "axes.spines.top": False, "axes.spines.right": False,
    "text.color": TEXT, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelsize": 9, "ytick.labelsize": 9, "grid.color": GRID_C,
    "grid.linewidth": 0.6, "legend.facecolor": BG, "legend.edgecolor": BORDER,
    "legend.fontsize": 9, "font.family": "DejaVu Sans", "font.size": 10,
})

FOOTER = "Source: merolagani.com  ·  NEPSE ETL Pipeline  ·  Informational use only"
_LM = _RM = _TM = _BM = 2.0 * cm
PAGE_W = A4[0] - _LM - _RM


# ── Chart helpers ──────────────────────────────────────────────────────────────

def _fmt_npr(ax):
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"Rs {x:,.0f}"))

def _shade(ax, x, y, color):
    ax.fill_between(x, y, float(y.min()) * 0.999, alpha=0.12, color=color, linewidth=0)

def _trend_badge(ax, y_vals):
    if len(y_vals) < 2: return
    pct = (float(y_vals.iloc[-1]) - float(y_vals.iloc[0])) / float(y_vals.iloc[0]) * 100
    txt, c = ("→ Flat", MUTED) if abs(pct) < 0.3 else (
             (f"↑ +{pct:.2f}%", UP_C) if pct > 0 else (f"↓ {pct:.2f}%", DOWN_C))
    ax.text(0.985, 0.97, txt, transform=ax.transAxes, ha="right", va="top",
            fontsize=9, color=c, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor=BG, edgecolor=c, linewidth=1.2))

def _mark_hl(ax, x, y):
    if len(y) < 3: return
    for idx, lbl, col, yoff in [
        (y.idxmax(), f"H  Rs {y.max():,.0f}", UP_C, 14),
        (y.idxmin(), f"L  Rs {y.min():,.0f}", DOWN_C, -18),
    ]:
        ax.annotate(lbl, xy=(x[idx], y[idx]), xytext=(0, yoff),
                    textcoords="offset points", ha="center", fontsize=8,
                    color=col, fontweight="bold",
                    arrowprops=dict(arrowstyle="-", color=col, lw=0.8))

def _plot_mas(ax, sub):
    handles = []
    for col, lbl, lw, ls in [("ma5","MA 5",1.6,"--"),("ma10","MA 10",1.6,"-."),("ma20","MA 20",1.8,":")]:
        v = sub[["fetched_at", col]].dropna() if col in sub.columns else pd.DataFrame()
        if len(v) >= 2:
            ln, = ax.plot(v["fetched_at"], v[col], color=MA_COLORS[col],
                          linewidth=lw, linestyle=ls, alpha=0.9, zorder=2, label=lbl)
            handles.append(ln)
    return handles

def _save(fig, path: Path) -> Path:
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.15, facecolor=BG)
    plt.close(fig)
    log.info(f"Chart: {path.name}")
    return path


# ── Individual charts ──────────────────────────────────────────────────────────

def _chart_individual_line(sym, sub, graphs_dir):
    color = PALETTE[hash(sym) % len(PALETTE)]
    fig, (ax_p, ax_v) = plt.subplots(2, 1, figsize=(12, 7.5),
        gridspec_kw={"height_ratios":[3,1],"hspace":0.35}, sharex=True)
    fig.patch.set_facecolor(BG)

    ln, = ax_p.plot(sub["fetched_at"], sub["close"], color=color, linewidth=2.5,
                    solid_capstyle="round", zorder=3, label="Close")
    _shade(ax_p, sub["fetched_at"], sub["close"], color)
    ax_p.scatter([sub["fetched_at"].iloc[-1]], [sub["close"].iloc[-1]],
                 color=color, s=55, zorder=4, edgecolors=BG, linewidth=2)
    _mark_hl(ax_p, sub["fetched_at"].reset_index(drop=True), sub["close"].reset_index(drop=True))
    _trend_badge(ax_p, sub["close"])
    ma_h = _plot_mas(ax_p, sub)
    if ma_h:
        ax_p.legend(handles=[ln]+ma_h, loc="upper left", framealpha=0.9, fontsize=8.5)

    last_c = sub["close"].iloc[-1]
    pct    = float(sub.get("pct_change_calc", pd.Series([0])).iloc[-1])
    ax_p.set_title(f"{sym}  ·  Close Price — Intraday Session",
                   fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax_p.text(0, -0.04,
        f"Close Rs {last_c:,.2f}  |  Change {'+'if pct>=0 else ''}{pct:.2f}%  |  "
        f"High Rs {sub['high'].max():,.2f}  |  Low Rs {sub['low'].min():,.2f}  |  "
        f"Vol {int(sub['volume'].iloc[-1]):,}",
        transform=ax_p.transAxes, fontsize=8, color=MUTED, va="top")
    _fmt_npr(ax_p); ax_p.set_ylabel("Price (NPR)", fontsize=9, color=MUTED)
    ax_p.grid(True, axis="y", linestyle="--", alpha=0.7)

    v_colors = [UP_C if v >= 0 else DOWN_C for v in sub.get("pct_change_calc", [0]*len(sub))]
    ax_v.bar(sub["fetched_at"], sub["volume"], color=v_colors, alpha=0.75, width=0.004)
    ax_v.set_ylabel("Volume", fontsize=8, color=MUTED)
    ax_v.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}K"))
    ax_v.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_v.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(ax_v.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    ax_v.set_xlabel("Time (NPT)", fontsize=9, color=MUTED)
    ax_v.grid(True, axis="y", linestyle="--", alpha=0.7)
    fig.text(0.5, 0.01, FOOTER, ha="center", fontsize=7, color=MUTED)
    fig.subplots_adjust(bottom=0.12, top=0.93)
    return _save(fig, graphs_dir / f"line_{sym}.png")


def _chart_overlay(df, graphs_dir):
    syms = [s for s in df["symbol"].unique() if s != "NEPSE"][:9]
    fig, ax = plt.subplots(figsize=(13, 6))
    for i, sym in enumerate(syms):
        sub = df[df["symbol"]==sym].sort_values("fetched_at")
        if sub.empty: continue
        norm = sub["close"] / sub["close"].iloc[0] * 100
        ax.plot(sub["fetched_at"], norm, label=sym,
                color=PALETTE[i%len(PALETTE)], linewidth=2,
                marker="o", markersize=3, solid_capstyle="round")
    ax.axhline(100, color=BORDER, linewidth=1, linestyle="--", zorder=0)
    ax.set_title("Close Price Overlay  ·  All Symbols (Indexed to 100)",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.set_xlabel("Time (NPT)", fontsize=9, color=MUTED)
    ax.set_ylabel("Indexed Price (Base=100)", fontsize=9, color=MUTED)
    ax.legend(ncol=3, framealpha=0.9); ax.grid(True, linestyle="--", alpha=0.7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate(); fig.subplots_adjust(bottom=0.15, top=0.92)
    return _save(fig, graphs_dir / "overlay_close_lines.png")


def _chart_pct_bars(df, graphs_dir):
    latest = (df.sort_values("fetched_at").groupby("symbol").last()
                .reset_index().sort_values("pct_change_calc"))
    colors_bar = [UP_C if v >= 0 else DOWN_C for v in latest["pct_change_calc"]]
    fig, ax = plt.subplots(figsize=(12, max(5, len(latest)*0.55+1.5)))
    bars = ax.barh(latest["symbol"], latest["pct_change_calc"],
                   color=colors_bar, edgecolor="white", height=0.6, alpha=0.9)
    off = latest["pct_change_calc"].abs().max() * 0.025
    for bar, val in zip(bars, latest["pct_change_calc"]):
        ax.text(val+(off if val>=0 else -off), bar.get_y()+bar.get_height()/2,
                f"{'+'if val>=0 else ''}{val:.2f}%", va="center",
                ha="left" if val>=0 else "right", fontsize=9, fontweight="bold", color=TEXT)
    ax.axvline(0, color=TEXT, linewidth=1.2)
    ax.set_title("Latest % Change vs Previous Close",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.set_xlabel("% Change", fontsize=9, color=MUTED)
    ax.grid(True, axis="x", linestyle="--", alpha=0.7)
    n_up = (latest["pct_change_calc"]>0).sum(); n_dn = (latest["pct_change_calc"]<0).sum()
    ax.text(0.99, 0.02, f"▲ {n_up} gainers  ·  ▼ {n_dn} losers",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color=MUTED,
            bbox=dict(boxstyle="round,pad=0.35", facecolor=BG, edgecolor=BORDER))
    fig.subplots_adjust(left=0.12, right=0.92, bottom=0.1, top=0.92)
    return _save(fig, graphs_dir / "pct_change_bars.png")


def _chart_candlestick(df, graphs_dir):
    top_syms = df.groupby("symbol")["symbol"].count().nlargest(4).index.tolist()
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle("Candlestick Charts  ·  Top 4 Symbols",
                 fontsize=14, fontweight="bold", color=TEXT, y=0.98)
    axes = axes.flatten()
    for ai, sym in enumerate(top_syms):
        ax  = axes[ai]
        sub = df[df["symbol"]==sym].sort_values("fetched_at").reset_index(drop=True)
        if len(sub) < 2:
            ax.text(0.5, 0.5, f"{sym}\nNo data", transform=ax.transAxes,
                    ha="center", va="center", color=MUTED, fontsize=11)
            continue
        for i, row in sub.iterrows():
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            clr = UP_C if c >= o else DOWN_C
            ax.plot([i,i], [l,h], color=clr, linewidth=1.2, zorder=2)
            ax.add_patch(Rectangle((i-0.35, min(o,c)), 0.7, max(abs(c-o),0.5),
                                   facecolor=clr, edgecolor="white",
                                   linewidth=0.5, alpha=0.9, zorder=3))
        ax.set_xlim(-0.8, len(sub)-0.2)
        lo, hi = sub["low"].min(), sub["high"].max()
        ax.set_ylim(lo-(hi-lo)*0.08, hi+(hi-lo)*0.08)
        n, step = len(sub), max(1, len(sub)//6)
        tidx = list(range(0, n, step))
        ax.set_xticks(tidx)
        ax.set_xticklabels([sub["fetched_at"].iloc[j].strftime("%H:%M") for j in tidx],
                            rotation=30, ha="right", fontsize=8)
        ax.set_title(sym, fontsize=12, fontweight="bold", color=TEXT, pad=8)
        ax.set_ylabel("NPR", fontsize=8, color=MUTED)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    for j in range(len(top_syms), 4): axes[j].set_visible(False)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return _save(fig, graphs_dir / "candlestick.png")


def _chart_volume(df, graphs_dir):
    top = df.groupby("symbol")["volume"].sum().nlargest(8).sort_values()
    fig, ax = plt.subplots(figsize=(12, max(5, len(top)*0.6+1.5)))
    bars = ax.barh(top.index, top.values,
                   color=[PALETTE[i%len(PALETTE)] for i in range(len(top))],
                   edgecolor="white", height=0.6, alpha=0.9)
    for bar, val in zip(bars, top.values):
        ax.text(val+top.max()*0.01, bar.get_y()+bar.get_height()/2,
                f"{val:,}", va="center", fontsize=9, color=MUTED, fontweight="bold")
    ax.set_title("Total Session Volume  ·  Top Symbols",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.set_xlabel("Shares Traded", fontsize=9, color=MUTED)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.grid(True, axis="x", linestyle="--", alpha=0.7)
    fig.subplots_adjust(left=0.12, right=0.92, bottom=0.1, top=0.92)
    return _save(fig, graphs_dir / "volume_bars.png")


def _chart_correlation(df, graphs_dir):
    pivot = (df.pivot_table(index="fetched_at", columns="symbol",
                            values="pct_change_calc", aggfunc="last").dropna(axis=1, thresh=2))
    if pivot.shape[1] < 2: return None
    corr = pivot.corr()
    fig, ax = plt.subplots(figsize=(max(8, len(corr)*0.9), max(7, len(corr)*0.8)))
    sns.heatmap(corr, mask=np.triu(np.ones_like(corr, dtype=bool)),
                cmap="RdYlGn", center=0, vmin=-1, vmax=1,
                annot=True, fmt=".2f", annot_kws={"size":9,"weight":"bold"},
                linewidths=0.8, linecolor=BORDER, ax=ax,
                cbar_kws={"shrink":0.8,"label":"Correlation"})
    ax.set_title("% Change Correlation  ·  All Symbols",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.tick_params(axis="x", rotation=45, labelsize=9)
    ax.tick_params(axis="y", rotation=0,  labelsize=9)
    fig.subplots_adjust(bottom=0.18, top=0.92)
    return _save(fig, graphs_dir / "correlation_heatmap.png")


def _chart_cum_return(df, graphs_dir):
    syms = [s for s in df["symbol"].unique() if s != "NEPSE"][:8]
    fig, ax = plt.subplots(figsize=(13, 6))
    for i, sym in enumerate(syms):
        sub = df[df["symbol"]==sym].sort_values("fetched_at")
        if not sub.empty:
            ax.plot(sub["fetched_at"], sub["cum_return_pct"], label=sym,
                    color=PALETTE[i%len(PALETTE)], linewidth=2.2, solid_capstyle="round")
    ax.axhline(0, color=MUTED, linewidth=1.2, linestyle="--", zorder=0)
    ax.set_title("Cumulative Return (%)  ·  Session",
                 fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax.set_xlabel("Time (NPT)", fontsize=9, color=MUTED)
    ax.set_ylabel("Cumulative %", fontsize=9, color=MUTED)
    ax.legend(ncol=3, framealpha=0.9); ax.grid(True, linestyle="--", alpha=0.7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate(); fig.subplots_adjust(bottom=0.15, top=0.92)
    return _save(fig, graphs_dir / "cumulative_return.png")


def _chart_summary_table(df, graphs_dir):
    latest = (df.sort_values("fetched_at").groupby("symbol").last()
                .reset_index()[["symbol","open","high","low","close","volume","pct_change_calc"]]
                .sort_values("pct_change_calc", ascending=False))
    latest.columns = ["Symbol","Open","High","Low","Close","Volume","Chg%"]
    for c in ("Open","High","Low","Close"):
        latest[c] = latest[c].map(lambda x: f"Rs {x:,.2f}")
    latest["Volume"] = latest["Volume"].map(lambda x: f"{x:,}")
    latest["Chg%"]   = latest["Chg%"].map(lambda x: f"{'+'if x>=0 else ''}{x:.2f}%")
    fig, ax = plt.subplots(figsize=(14, max(4, len(latest)*0.52+1.8)))
    ax.axis("off")
    tbl = ax.table(cellText=latest.values, colLabels=latest.columns,
                   cellLoc="center", loc="center", bbox=[0,0,1,1])
    tbl.auto_set_font_size(False); tbl.set_fontsize(10)
    for (r, c_i), cell in tbl.get_celld().items():
        cell.set_edgecolor(BORDER); cell.set_linewidth(0.5)
        if r == 0:
            cell.set_facecolor("#BBDEFB")
            cell.set_text_props(color=TEXT, fontweight="bold", fontsize=10)
        else:
            cell.set_facecolor("#FFFFFF" if r%2==0 else "#F5F5F5")
            cell.set_text_props(color=TEXT, fontsize=9)
        if c_i == 6 and r > 0:
            val = latest.iloc[r-1]["Chg%"]
            cell.set_facecolor("#E8F5E9" if "+" in val else "#FFEBEE")
            cell.set_text_props(color=UP_C if "+" in val else DOWN_C, fontweight="bold")
    ax.set_title("NEPSE  ·  Session Summary  ·  Latest OHLCV",
                 fontsize=13, fontweight="bold", color=TEXT, pad=14)
    return _save(fig, graphs_dir / "summary_table.png")


def _chart_nepse_index(df, graphs_dir):
    nepse = df[df["symbol"]=="NEPSE"].sort_values("fetched_at")
    if nepse.empty: return None
    color = PALETTE[0]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8.5),
        gridspec_kw={"height_ratios":[3,1],"hspace":0.35}, sharex=True)
    ax1.plot(nepse["fetched_at"], nepse["close"], color=color, linewidth=2.5,
             solid_capstyle="round", zorder=3)
    _shade(ax1, nepse["fetched_at"], nepse["close"], color)
    _mark_hl(ax1, nepse["fetched_at"].reset_index(drop=True),
             nepse["close"].reset_index(drop=True))
    _trend_badge(ax1, nepse["close"]); _plot_mas(ax1, nepse)
    ax1.set_title("NEPSE Index  ·  Intraday Session",
                  fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=12)
    ax1.set_ylabel("Index Value", fontsize=9, color=MUTED)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax1.grid(True, linestyle="--", alpha=0.7)
    v_colors = [UP_C if v >= 0 else DOWN_C for v in nepse["pct_change_calc"]]
    ax2.bar(nepse["fetched_at"], nepse["volume"], color=v_colors, alpha=0.8, width=0.003)
    ax2.set_ylabel("Volume", fontsize=8, color=MUTED)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}K"))
    ax2.set_xlabel("Time (NPT)", fontsize=9, color=MUTED)
    ax2.grid(True, linestyle="--", alpha=0.7)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate(); fig.subplots_adjust(bottom=0.12, top=0.93)
    return _save(fig, graphs_dir / "nepse_index.png")


def generate_all_charts(df: pd.DataFrame, date_str: str | None = None) -> dict[str, Path]:
    graphs_dir, _ = get_session_dirs(date_str)
    charts = {}
    for sym in df["symbol"].unique():
        sub = df[df["symbol"]==sym].sort_values("fetched_at").reset_index(drop=True)
        if len(sub) >= 2:
            try: charts[f"line_{sym}"] = _chart_individual_line(sym, sub, graphs_dir)
            except Exception as e: log.error(f"Chart {sym}: {e}", exc_info=True)
    for key, fn in [
        ("overlay",_chart_overlay), ("pct_bars",_chart_pct_bars),
        ("candlestick",_chart_candlestick), ("volume",_chart_volume),
        ("correlation",_chart_correlation), ("cum_return",_chart_cum_return),
        ("summary",_chart_summary_table), ("nepse_index",_chart_nepse_index),
    ]:
        try:
            p = fn(df, graphs_dir)
            if p: charts[key] = p
        except Exception as e: log.error(f"Chart '{key}': {e}", exc_info=True)
    log.info(f"Generated {len(charts)} charts → {graphs_dir}")
    return charts


# ── PDF helpers ────────────────────────────────────────────────────────────────

def _styles():
    base = getSampleStyleSheet()
    def ps(name, **kw): return ParagraphStyle(name, parent=base["Normal"], **kw)
    return {
        "Cover":   ps("Cover",   fontSize=40, fontName="Helvetica-Bold",   textColor=C["accent"],  alignment=TA_CENTER, leading=48),
        "CoverSub":ps("CoverSub",fontSize=13, fontName="Helvetica",        textColor=C["muted"],   alignment=TA_CENTER, leading=20),
        "Banner":  ps("Banner",  fontSize=11, fontName="Helvetica-Bold",   textColor=C["white"],   leading=16, leftIndent=8),
        "Sub":     ps("Sub",     fontSize=11, fontName="Helvetica-Bold",   textColor=C["accent"],  leading=16, spaceBefore=4),
        "Body":    ps("Body",    fontSize=9.5,fontName="Helvetica",        textColor=C["text"],    leading=15),
        "Interp":  ps("Interp",  fontSize=8.5,fontName="Helvetica-Oblique",textColor=C["muted"],   leading=13, leftIndent=10),
        "Small":   ps("Small",   fontSize=7.5,fontName="Helvetica",        textColor=C["muted"],   leading=11, alignment=TA_CENTER),
        "Footer":  ps("Footer",  fontSize=7.5,fontName="Helvetica",        textColor=C["muted"],   alignment=TA_CENTER, leading=11),
        "KPIVal":  ps("KPIVal",  fontSize=22, fontName="Helvetica-Bold",   textColor=C["kpi_val"], alignment=TA_CENTER, leading=28),
        "KPILbl":  ps("KPILbl",  fontSize=8,  fontName="Helvetica",        textColor=C["kpi_lbl"], alignment=TA_CENTER, leading=11),
    }

def _sp(pts=12): return Spacer(1, pts)
def _hr(c=None, thick=0.5): return HRFlowable(width="100%",thickness=thick,color=c or C["border"],spaceBefore=4,spaceAfter=4)

def _banner(text, styles):
    tbl = Table([[Paragraph(text, styles["Banner"])]], colWidths=[PAGE_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),C["accent2"]),
        ("TOPPADDING",(0,0),(-1,-1),9), ("BOTTOMPADDING",(0,0),(-1,-1),9),
        ("LEFTPADDING",(0,0),(-1,-1),12), ("RIGHTPADDING",(0,0),(-1,-1),12),
    ]))
    return [_sp(10), tbl, _sp(8)]

def _img_block(path, caption, styles, max_h=9.5*cm):
    if not path or not path.exists():
        return [_sp(6), Paragraph(f"[Chart unavailable: {caption}]", styles["Small"]), _sp(6)]
    img = Image(str(path))
    scale = min(PAGE_W/img.imageWidth, max_h/img.imageHeight, 1.0)
    img.drawWidth = img.imageWidth*scale; img.drawHeight = img.imageHeight*scale
    return [_sp(6), img, _sp(4), Paragraph(f"<i>{caption}</i>", styles["Small"]), _sp(16)]

def _kpi_cards(metrics, styles):
    n = len(metrics); cw = [PAGE_W/n]*n
    tbl = Table(
        [[Paragraph(v, styles["KPIVal"]) for v,_ in metrics],
         [Paragraph(l, styles["KPILbl"]) for _,l in metrics]], colWidths=cw)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),C["kpi_bg"]),
        ("BOX",(0,0),(-1,-1),0.5,C["border"]),
        ("INNERGRID",(0,0),(-1,-1),0.4,colors.HexColor("#1e3a5f")),
        ("TOPPADDING",(0,0),(-1,-1),14), ("BOTTOMPADDING",(0,0),(-1,-1),14),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
    ]))
    return tbl

def _stat_strip(items, styles):
    hdrs = [Paragraph(f"<b>{h}</b>", styles["Small"]) for h,_,_ in items]
    vals = []
    for _, val, is_chg in items:
        if is_chg:
            col = C["green"] if ("▲" in val or ("+" in val and "▼" not in val)) else C["red"]
            p = Paragraph(f"<b>{val}</b>",
                ParagraphStyle("_c", parent=styles["Small"],
                               textColor=col, fontName="Helvetica-Bold", alignment=TA_CENTER))
        else:
            p = Paragraph(val, styles["Small"])
        vals.append(p)
    cw = [PAGE_W/len(items)]*len(items)
    tbl = Table([hdrs, vals], colWidths=cw)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),C["head"]), ("BACKGROUND",(0,1),(-1,1),C["panel"]),
        ("BOX",(0,0),(-1,-1),0.5,C["border"]), ("INNERGRID",(0,0),(-1,-1),0.3,C["border"]),
        ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("ALIGN",(0,0),(-1,-1),"CENTER"), ("FONTSIZE",(0,0),(-1,-1),8),
    ]))
    return tbl

def _df_table(df_slice, styles):
    header = [Paragraph(f"<b>{c}</b>", styles["Small"]) for c in df_slice.columns]
    rows   = [header] + [[Paragraph(str(v), styles["Small"]) for v in row]
                          for _, row in df_slice.iterrows()]
    cw = [PAGE_W/len(df_slice.columns)]*len(df_slice.columns)
    tbl = Table(rows, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),C["head"]),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, C["panel2"]]),
        ("TEXTCOLOR",(0,0),(-1,-1),C["text"]),
        ("BOX",(0,0),(-1,-1),0.5,C["border"]), ("INNERGRID",(0,0),(-1,-1),0.3,C["border"]),
        ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("ALIGN",(0,0),(-1,-1),"CENTER"), ("FONTSIZE",(0,0),(-1,-1),7.5),
    ]))
    return tbl


# ── PDF builder ────────────────────────────────────────────────────────────────

def generate_report(
    charts: dict[str, Path],
    df: pd.DataFrame,
    date_str: str | None = None,
    out_name: str | None = None,
    email_recipients: list[str] | None = None,
    email_cc: list[str] | None = None,
) -> Path:
    """Build PDF, fire notification and send email."""
    _, session_dir = get_session_dirs(date_str)
    out_name = out_name or f"NEPSE_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    out_path = session_dir / out_name
    styles   = _styles()
    now_dt   = datetime.now()

    doc   = SimpleDocTemplate(str(out_path), pagesize=A4,
                               leftMargin=_LM, rightMargin=_RM,
                               topMargin=_TM, bottomMargin=_BM,
                               title="NEPSE ETL Report", author="NEPSE ETL Pipeline")
    story = []

    # Cover
    story += [_sp(3*cm),
              Paragraph("NEPSE", styles["Cover"]), _sp(6),
              Paragraph("Live ETL  ·  Analytics Report", styles["CoverSub"]), _sp(4),
              Paragraph(now_dt.strftime("%A, %d %B %Y  |  %H:%M NPT"), styles["CoverSub"])]

    summary_dict = {}
    if not df.empty:
        mn = df["fetched_at"].min().strftime("%d %b  %H:%M")
        mx = df["fetched_at"].max().strftime("%d %b  %H:%M")
        story += [_sp(4), Paragraph(f"Session window: {mn} – {mx} NPT", styles["CoverSub"])]
        lat = df.sort_values("fetched_at").groupby("symbol").last()
        n_sym, t_vol = df["symbol"].nunique(), int(lat["volume"].sum())
        avg_ch = float(lat["pct_change_calc"].mean())
        n_up   = int((lat["pct_change_calc"]>0).sum())
        n_dn   = int((lat["pct_change_calc"]<0).sum())
        summary_dict = {"n_symbols":n_sym,"total_volume":t_vol,
                        "gainers":n_up,"losers":n_dn,"avg_change":avg_ch}
        story += [_sp(28), _hr(C["accent"],thick=2), _sp(20),
                  _kpi_cards([(f"{n_sym}","Symbols Tracked"),(f"{t_vol:,}","Total Volume"),
                               (f"{n_up}/{n_dn}","Gainers/Losers"),(f"{avg_ch:+.2f}%","Avg % Chg")],
                             styles)]
    story += [_sp(28), _hr(), _sp(8),
              Paragraph("Generated by NEPSE ETL Pipeline  ·  merolagani.com  ·  Informational use only.", styles["Footer"]),
              PageBreak()]

    # Section 1: Individual charts
    story += _banner("1.  Individual Company Price Charts", styles)
    story.append(Paragraph(
        "Intraday close price with volume bars. MA 5/10/20 overlaid. Trend badge and H/L annotations shown.", styles["Body"]))
    story.append(_sp(10))
    sym_keys = sorted(k for k in charts if k.startswith("line_"))
    for idx, key in enumerate(sym_keys):
        sym = key.replace("line_", "")
        sub = df[df["symbol"]==sym].sort_values("fetched_at")
        hdr = [Paragraph(f"1.{idx+1}  {sym}", styles["Sub"])]
        if not sub.empty and len(sub) >= 2:
            first_c, last_c = float(sub["close"].iloc[0]), float(sub["close"].iloc[-1])
            pct = (last_c-first_c)/first_c*100 if first_c > 0 else 0
            hi, lo, vol = float(sub["high"].max()), float(sub["low"].min()), int(sub["volume"].iloc[-1])
            sign = "▲" if pct >= 0 else "▼"
            hdr += [_sp(4),
                    _stat_strip([
                        ("Open", f"Rs {first_c:,.2f}", False), ("High", f"Rs {hi:,.2f}", False),
                        ("Low",  f"Rs {lo:,.2f}",  False),   ("Close",f"Rs {last_c:,.2f}",False),
                        ("Change",f"{sign} {abs(pct):.2f}%",True), ("Volume",f"{vol:,}",False),
                    ], styles), _sp(4),
                    Paragraph(
                        f"{sym} {'gained' if pct>=0 else 'lost'} {abs(pct):.2f}% this session, "
                        f"trading Rs {lo:,.2f}–{hi:,.2f}. Last close Rs {last_c:,.2f}, Vol {vol:,}.",
                        styles["Interp"])]
        story.append(KeepTogether(hdr + _img_block(
            charts[key], f"Figure 1.{idx+1}  —  {sym}  Close, MAs & Volume", styles)))
        if (idx+1)%2==0 and idx < len(sym_keys)-1: story.append(PageBreak())
        else: story.append(_sp(10))
    story.append(PageBreak())

    # Sections 2–9
    sections = [
        ("2.  NEPSE Index  ·  Intraday Overview",
         "The NEPSE index gives a macro view of the overall session.",
         [("nepse_index","Figure 2 — NEPSE Index: Close, MAs & Volume", 11.0*cm)]),

        ("3.  Close Price Overlay  ·  All Symbols",
         "Prices indexed to 100 at session open for direct comparison.",
         [("overlay","Figure 3 — Close Price Overlay (Indexed to 100)", 9.0*cm)]),

        ("4.  Returns & Cumulative Performance",
         "% change vs previous close and compounding returns over the session.",
         [("pct_bars","Figure 4 — Latest % Change vs Previous Close", None),
          ("cum_return","Figure 5 — Cumulative Return (%) Over Session", None)]),

        ("5.  Candlestick Analysis  ·  Top Symbols",
         "Green = bullish (close ≥ open). Red = bearish. Long wicks = price rejection.",
         [("candlestick","Figure 6 — Candlestick Charts: Top 4 Symbols", 13.0*cm)]),

        ("6.  Volume & Correlation",
         "High volume on a rising stock confirms demand. Heatmap: +1 = co-moving, -1 = opposite.",
         [("volume","Figure 7 — Total Session Volume by Symbol", None),
          ("correlation","Figure 8 — % Change Correlation Heatmap", None)]),

        ("7.  Session Summary Table",
         "Latest OHLCV snapshot sorted by % change. Green = positive, red = negative.",
         [("summary","Figure 9 — OHLCV Summary (Latest Values)", 11.0*cm)]),
    ]
    for title, body_txt, figs in sections:
        story += _banner(title, styles)
        story.append(Paragraph(body_txt, styles["Body"])); story.append(_sp(6))
        for key, caption, max_h in figs:
            if key in charts:
                kw = {"max_h": max_h} if max_h else {}
                story += _img_block(charts[key], caption, styles, **kw)
        story.append(PageBreak())

    # Section 8: Statistics
    story += _banner("8.  Descriptive Statistics", styles)
    story.append(Paragraph("Count, mean, std, min, quartiles, max for all numeric columns.", styles["Body"]))
    story.append(_sp(8))
    if not df.empty:
        cols = [c for c in ["open","high","low","close","volume","pct_change_calc","range","ma5","ma10","ma20"] if c in df.columns]
        desc = df[cols].describe().round(2).reset_index()
        desc.columns = ["Stat"] + cols
        story.append(_df_table(desc, styles))
    story.append(PageBreak())

    # Section 9: Data sample
    story += _banner("9.  Cleaned Data Sample  ·  Latest 20 Rows", styles)
    story.append(Paragraph("The 20 most recently fetched rows from this session.", styles["Body"]))
    story.append(_sp(8))
    if not df.empty:
        ma_cols = [c for c in ["ma5","ma10","ma20"] if c in df.columns]
        show    = [c for c in ["fetched_at","symbol","open","high","low","close","volume","pct_change_calc","direction"]+ma_cols if c in df.columns]
        samp    = df.sort_values("fetched_at", ascending=False).head(20)[show].copy()
        samp["fetched_at"] = samp["fetched_at"].dt.strftime("%H:%M:%S")
        for c in ["open","high","low","close"]+ma_cols:
            if c in samp: samp[c] = samp[c].map(lambda x: f"{float(x):,.2f}" if pd.notna(x) else "—")
        if "volume" in samp: samp["volume"] = samp["volume"].map(lambda x: f"{int(x):,}")
        if "pct_change_calc" in samp:
            samp["pct_change_calc"] = samp["pct_change_calc"].map(
                lambda x: f"{'+'if float(x)>=0 else ''}{float(x):.2f}%" if pd.notna(x) else "—")
        samp.columns = [c.replace("_calc","").replace("_"," ").title() for c in samp.columns]
        story.append(_df_table(samp, styles))

    story += [_sp(28), _hr(), _sp(8),
              Paragraph(f"NEPSE ETL Pipeline  ·  {now_dt.strftime('%d %b %Y  %H:%M:%S')} NPT  ·  merolagani.com  ·  Informational use only.", styles["Footer"])]

    doc.build(story)
    log.info(f"PDF saved: {out_path}")

    # Notify + email
    try:
        from notifier import notify_async
        notify_async("NEPSE Report Ready", f"PDF saved: {out_path.name}", pdf_path=out_path)
    except Exception as e:
        log.debug(f"Notification error: {e}")

    try:
        from notifier import send_report
        ok = send_report(out_path, recipients=email_recipients, cc=email_cc,
                         summary=summary_dict or None)
        log.info("Report emailed." if ok else "Email not sent — check config.")
    except Exception as e:
        log.error(f"Email error: {e}", exc_info=True)

    return out_path


def load_cleaned() -> pd.DataFrame:
    if not CLEANED_CSV.exists():
        raise FileNotFoundError(f"cleaned.csv not found at {CLEANED_CSV}")
    df = pd.read_csv(CLEANED_CSV, parse_dates=["fetched_at","date"])
    log.info(f"Loaded {len(df)} rows from cleaned.csv")
    return df


if __name__ == "__main__":
    df_     = load_cleaned()
    charts_ = generate_all_charts(df_)
    path_   = generate_report(charts_, df_)
    print(f"Report: {path_}")
