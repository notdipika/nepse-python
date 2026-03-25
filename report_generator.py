"""
report_generator.py  ─  Stage 5: PDF Report  (v2)

Improvements:
  • Richer colour scheme: accent bands, coloured KPI cards, section dividers
  • Fixed text overlap: KeepTogether guards, explicit Spacer budgeting
  • MA information included in per-symbol summary text
  • Cross-platform popup notification (Windows / macOS / Linux)
"""
import os
import sys
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image,
    Table, TableStyle, PageBreak, HRFlowable,
    KeepTogether, CondPageBreak,
)

from config import CLEANED_CSV, get_session_dirs
from logger import get_logger

log = get_logger("report_generator")

# ─── Colour palette ───────────────────────────────────────────────────────────
C_BG      = colors.HexColor("#FAFAF8")
C_PANEL   = colors.HexColor("#F4F1ED")
C_PANEL2  = colors.HexColor("#EBF3FA")      # light blue tint for alt rows
C_BORDER  = colors.HexColor("#DDD8D0")
C_TEXT    = colors.HexColor("#1A1A2E")
C_MUTED   = colors.HexColor("#7A7670")
C_ACCENT  = colors.HexColor("#2E6DA4")      # deep blue
C_ACCENT2 = colors.HexColor("#1565C0")      # header fills
C_GREEN   = colors.HexColor("#2E7D32")
C_RED     = colors.HexColor("#B71C1C")
C_AMBER   = colors.HexColor("#E65100")
C_HEAD    = colors.HexColor("#D6E4F0")      # table header fill
C_KPI_BG  = colors.HexColor("#1A3A5C")      # dark card bg for KPIs
C_KPI_VAL = colors.HexColor("#64B5F6")      # KPI value colour
C_WHITE   = colors.white

PAGE_W    = A4[0] - 4 * cm                  # usable content width


# ─── Style sheet ─────────────────────────────────────────────────────────────

def _styles():
    base = getSampleStyleSheet()
    S = {
        "Cover":    ParagraphStyle("Cover",    parent=base["Normal"],
                                   fontSize=36, fontName="Helvetica-Bold",
                                   textColor=C_ACCENT, alignment=TA_CENTER,
                                   spaceAfter=6, leading=42),
        "CoverSub": ParagraphStyle("CoverSub", parent=base["Normal"],
                                   fontSize=14, fontName="Helvetica",
                                   textColor=C_MUTED, alignment=TA_CENTER,
                                   spaceAfter=3, leading=18),
        "Section":  ParagraphStyle("Section",  parent=base["Normal"],
                                   fontSize=13, fontName="Helvetica-Bold",
                                   textColor=C_WHITE, spaceBefore=6, spaceAfter=0,
                                   leftIndent=8, leading=18),
        "Sub":      ParagraphStyle("Sub",      parent=base["Normal"],
                                   fontSize=11, fontName="Helvetica-Bold",
                                   textColor=C_ACCENT, spaceBefore=8, spaceAfter=3,
                                   leading=14),
        "Body":     ParagraphStyle("Body",     parent=base["Normal"],
                                   fontSize=9, fontName="Helvetica",
                                   textColor=C_TEXT, leading=14, spaceAfter=4),
        "Interp":   ParagraphStyle("Interp",   parent=base["Normal"],
                                   fontSize=8.5, fontName="Helvetica-Oblique",
                                   textColor=C_MUTED, leading=13, spaceAfter=4,
                                   leftIndent=12),
        "Small":    ParagraphStyle("Small",    parent=base["Normal"],
                                   fontSize=7.5, fontName="Helvetica",
                                   textColor=C_MUTED, leading=11),
        "Footer":   ParagraphStyle("Footer",   parent=base["Normal"],
                                   fontSize=7, fontName="Helvetica",
                                   textColor=C_MUTED, alignment=TA_CENTER, leading=10),
        "Metric":   ParagraphStyle("Metric",   parent=base["Normal"],
                                   fontSize=22, fontName="Helvetica-Bold",
                                   textColor=C_KPI_VAL, alignment=TA_CENTER, leading=26),
        "MLabel":   ParagraphStyle("MLabel",   parent=base["Normal"],
                                   fontSize=7.5, fontName="Helvetica",
                                   textColor=colors.HexColor("#AECDE8"),
                                   alignment=TA_CENTER, leading=10),
    }
    return S


# ─── Helpers ─────────────────────────────────────────────────────────────────

def hr(color=C_BORDER, t=0.5, before=3, after=6):
    return HRFlowable(width="100%", thickness=t, color=color,
                      spaceBefore=before, spaceAfter=after)


def section_banner(text: str, styles) -> list:
    """Coloured accent bar with white section title inside it."""
    tbl = Table([[Paragraph(text, styles["Section"])]], colWidths=[PAGE_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_ACCENT2),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ("ROUNDEDCORNERS", [4]),
    ]))
    return [tbl, Spacer(1, 8)]


def add_img(path: Path, caption: str, styles,
            max_w: float = PAGE_W, max_h: float = 9.5 * cm) -> list:
    """Return [Image, caption_paragraph, spacer] clamped to max dimensions."""
    if not path or not path.exists():
        return [Paragraph(f"[Chart unavailable: {caption}]", styles["Small"]),
                Spacer(1, 4)]
    img        = Image(str(path))
    scale      = min(max_w / img.imageWidth, max_h / img.imageHeight, 1.0)
    img.drawWidth  = img.imageWidth  * scale
    img.drawHeight = img.imageHeight * scale
    return [
        img,
        Spacer(1, 2),
        Paragraph(f"<i>{caption}</i>", styles["Small"]),
        Spacer(1, 10),
    ]


def kpi_cards(metrics: list[tuple[str, str]], styles) -> Table:
    """Dark-card KPI row: [(value, label), ...]"""
    n   = len(metrics)
    cw  = [PAGE_W / n] * n
    row_val = [Paragraph(v, styles["Metric"]) for v, _ in metrics]
    row_lbl = [Paragraph(l, styles["MLabel"]) for _, l in metrics]
    t   = Table([row_val, row_lbl], colWidths=cw)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_KPI_BG),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, colors.HexColor("#2A4A6A")),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("ROUNDEDCORNERS", [6]),
    ]))
    return t


def stat_row_table(label_vals: list[tuple[str, str, bool]], styles) -> Table:
    """
    Compact horizontal stat table for per-symbol stats.
    label_vals: [(label, value, is_change_col), ...]
    """
    headers = [Paragraph(f"<b>{lbl}</b>", styles["Small"]) for lbl, _, _ in label_vals]
    vals    = []
    for lbl, val, is_chg in label_vals:
        if is_chg:
            colour = C_GREEN if "+" in val or (val and val[0] not in ("-", "▼")) else C_RED
            if "▼" in val:
                colour = C_RED
            elif "▲" in val:
                colour = C_GREEN
            p = Paragraph(f"<b>{val}</b>",
                          ParagraphStyle("chg", parent=styles["Small"],
                                         textColor=colour, fontName="Helvetica-Bold",
                                         alignment=TA_CENTER))
        else:
            p = Paragraph(val, styles["Small"])
        vals.append(p)

    cw = [PAGE_W / len(label_vals)] * len(label_vals)
    t  = Table([headers, vals], colWidths=cw)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  C_HEAD),
        ("BACKGROUND",    (0, 1), (-1, 1),  C_PANEL),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, C_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
    ]))
    return t


def df_table(df_slice: pd.DataFrame, styles) -> Table:
    header = [Paragraph(f"<b>{c}</b>", styles["Small"]) for c in df_slice.columns]
    rows   = [header]
    for _, row in df_slice.iterrows():
        rows.append([Paragraph(str(v), styles["Small"]) for v in row])
    cw = [PAGE_W / len(df_slice.columns)] * len(df_slice.columns)
    t  = Table(rows, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  C_HEAD),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  C_TEXT),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_BG, C_PANEL2]),
        ("TEXTCOLOR",     (0, 1), (-1, -1), C_TEXT),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, C_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
    ]))
    return t


# ─── Main report builder ──────────────────────────────────────────────────────

def generate_report(charts: dict[str, Path],
                    df: pd.DataFrame,
                    date_str: str | None = None,
                    out_name: str | None = None) -> Path:

    _, session_dir = get_session_dirs(date_str)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not out_name:
        out_name = f"NEPSE_Report_{ts}.pdf"
    out_path = session_dir / out_name

    styles = _styles()
    doc    = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title="NEPSE ETL Report", author="NEPSE ETL Pipeline",
    )

    story = []

    # ─── Cover ───────────────────────────────────────────────────────────────
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph("NEPSE", styles["Cover"]))
    story.append(Paragraph("Live ETL  ·  Analytics Report", styles["CoverSub"]))
    story.append(Spacer(1, 0.4 * cm))

    gen_dt = datetime.now().strftime("%A, %d %B %Y  |  %H:%M NPT")
    story.append(Paragraph(gen_dt, styles["CoverSub"]))

    if not df.empty:
        mn = df["fetched_at"].min().strftime("%d %b  %H:%M")
        mx = df["fetched_at"].max().strftime("%d %b  %H:%M")
        story.append(Paragraph(f"Session window: {mn} – {mx} NPT",
                               styles["CoverSub"]))

    story.append(Spacer(1, 0.6 * cm))
    story.append(hr(C_ACCENT, t=2))
    story.append(Spacer(1, 0.5 * cm))

    # KPI cards
    if not df.empty:
        lat    = df.sort_values("fetched_at").groupby("symbol").last()
        t_vol  = int(lat["volume"].sum())
        avg_ch = float(lat["pct_change_calc"].mean())
        n_up   = int((lat["pct_change_calc"] > 0).sum())
        n_dn   = int((lat["pct_change_calc"] < 0).sum())
        n_sym  = df["symbol"].nunique()
        story.append(kpi_cards([
            (f"{n_sym}",         "Symbols Tracked"),
            (f"{t_vol:,}",       "Total Volume"),
            (f"{n_up} / {n_dn}", "Gainers / Losers"),
            (f"{avg_ch:+.2f}%",  "Avg % Change"),
        ], styles))

    story.append(Spacer(1, 1.2 * cm))
    story.append(hr(C_BORDER))
    story.append(Paragraph(
        "Generated by NEPSE ETL Pipeline  ·  Data source: merolagani.com  ·  "
        "For informational use only.", styles["Footer"]))
    story.append(PageBreak())

    # ─── Sec 1: Per-company charts ────────────────────────────────────────────
    story += section_banner("1.  Individual Company Price Charts", styles)
    story.append(Paragraph(
        "Each chart shows the intraday close price, moving averages (MA 5 / 10 / 20), "
        "session high/low annotations, a trend badge, and volume bars. "
        "Green volume bars indicate positive periods; red bars indicate negative ones.",
        styles["Body"]))
    story.append(Spacer(1, 6))

    sym_keys = sorted(k for k in charts if k.startswith("line_"))
    for idx, key in enumerate(sym_keys):
        sym  = key.replace("line_", "")
        path = charts[key]
        sub  = df[df["symbol"] == sym].sort_values("fetched_at")

        # Per-symbol stats row
        stats_content = []
        if not sub.empty and len(sub) >= 2:
            first_c = float(sub["close"].iloc[0])
            last_c  = float(sub["close"].iloc[-1])
            pct     = (last_c - first_c) / first_c * 100 if first_c > 0 else 0
            hi      = float(sub["high"].max())
            lo      = float(sub["low"].min())
            vol     = int(sub["volume"].iloc[-1])
            sign    = "▲" if pct >= 0 else "▼"

            # MA values (latest non-null)
            ma5  = sub["ma5"].dropna().iloc[-1]  if "ma5"  in sub.columns and not sub["ma5"].dropna().empty  else None
            ma10 = sub["ma10"].dropna().iloc[-1] if "ma10" in sub.columns and not sub["ma10"].dropna().empty else None
            ma20 = sub["ma20"].dropna().iloc[-1] if "ma20" in sub.columns and not sub["ma20"].dropna().empty else None

            ma_str  = "  |  ".join(filter(None, [
                f"MA5 Rs {ma5:,.2f}"  if ma5  is not None else None,
                f"MA10 Rs {ma10:,.2f}" if ma10 is not None else None,
                f"MA20 Rs {ma20:,.2f}" if ma20 is not None else None,
            ]))
            interp_dir = "gained" if pct >= 0 else "lost"
            note = (
                f"{sym} {interp_dir} {abs(pct):.2f}% this session, trading between "
                f"Rs {lo:,.2f} and Rs {hi:,.2f}. "
                f"Last close: Rs {last_c:,.2f}  |  Volume: {vol:,}.  "
                + (f"Moving averages — {ma_str}." if ma_str else "")
            )

            stats_content = [
                Paragraph(f"1.{idx+1}  {sym}", styles["Sub"]),
                stat_row_table([
                    ("Open",      f"Rs {first_c:,.2f}", False),
                    ("High",      f"Rs {hi:,.2f}",      False),
                    ("Low",       f"Rs {lo:,.2f}",      False),
                    ("Close",     f"Rs {last_c:,.2f}",  False),
                    ("Change",    f"{sign} {abs(pct):.2f}%", True),
                    ("Volume",    f"{vol:,}",            False),
                ], styles),
                Spacer(1, 4),
                Paragraph(note, styles["Interp"]),
            ]
        else:
            stats_content = [Paragraph(f"1.{idx+1}  {sym}", styles["Sub"])]

        img_block = add_img(path, f"Figure 1.{idx+1} — {sym}  Close Price, MAs & Volume",
                            styles, max_h=9 * cm)

        story.append(KeepTogether(stats_content + img_block))
        story.append(Spacer(1, 4))

        # Page break every 2 charts
        if (idx + 1) % 2 == 0 and idx < len(sym_keys) - 1:
            story.append(PageBreak())

    story.append(PageBreak())

    # ─── Sec 2: NEPSE Index ───────────────────────────────────────────────────
    story += section_banner("2.  NEPSE Index  ·  Intraday Overview", styles)
    story.append(Paragraph(
        "The NEPSE index chart gives a macro view of the overall market session. "
        "A rising index with increasing green volume bars confirms broad-based buying. "
        "MA overlays on the index chart highlight trend direction changes.",
        styles["Body"]))
    if "nepse_index" in charts:
        story += add_img(charts["nepse_index"],
                         "Figure 2 — NEPSE Index: Close, MAs & Volume (Intraday)", styles)
    story.append(PageBreak())

    # ─── Sec 3: Close overlay ─────────────────────────────────────────────────
    story += section_banner("3.  Close Price Overlay  ·  All Symbols", styles)
    story.append(Paragraph(
        "Overlaying all symbols reveals relative performance and synchronised moves. "
        "Symbols that deviate sharply from the pack may be reacting to company-specific "
        "news or circuit-breaker activity.",
        styles["Body"]))
    if "overlay" in charts:
        story += add_img(charts["overlay"],
                         "Figure 3 — Close Price Overlay: All Tracked Symbols", styles)
    story.append(PageBreak())

    # ─── Sec 4: Returns ───────────────────────────────────────────────────────
    story += section_banner("4.  Returns & Cumulative Performance", styles)
    story.append(Paragraph(
        "The % change bar chart shows each symbol's latest return vs its previous close. "
        "The cumulative return chart tracks how returns have compounded; "
        "a steep late-session climb suggests momentum buying at close.",
        styles["Body"]))
    if "pct_bars" in charts:
        story += add_img(charts["pct_bars"],
                         "Figure 4 — Latest % Change vs Previous Close", styles)
    if "cum_return" in charts:
        story += add_img(charts["cum_return"],
                         "Figure 5 — Cumulative Return (%) Over Session", styles)
    story.append(PageBreak())

    # ─── Sec 5: Candlestick ───────────────────────────────────────────────────
    story += section_banner("5.  Candlestick Analysis  ·  Top Symbols", styles)
    story.append(Paragraph(
        "Candlesticks show the OHLC relationship per polling interval. "
        "A long green body signals strong buying; a long upper wick on a red candle "
        "suggests sellers regained control after an initial push higher.",
        styles["Body"]))
    if "candlestick" in charts:
        story += add_img(charts["candlestick"],
                         "Figure 6 — Candlestick Charts: Top 4 Symbols",
                         styles, max_h=12 * cm)
    story.append(PageBreak())

    # ─── Sec 6: Volume & Correlation ─────────────────────────────────────────
    story += section_banner("6.  Volume & Correlation", styles)
    story.append(Paragraph(
        "High volume in a rising stock confirms demand. "
        "The correlation heatmap shows how closely % changes move together — "
        "values near 1 indicate co-movement; near 0 means independent price action.",
        styles["Body"]))
    if "volume" in charts:
        story += add_img(charts["volume"],
                         "Figure 7 — Total Session Volume by Symbol", styles)
    if "correlation" in charts:
        story += add_img(charts["correlation"],
                         "Figure 8 — % Change Correlation Heatmap", styles)
    story.append(PageBreak())

    # ─── Sec 7: Summary table ─────────────────────────────────────────────────
    story += section_banner("7.  Session Summary Table", styles)
    story.append(Paragraph(
        "Latest OHLCV snapshot for all tracked symbols, sorted by % change. "
        "Green figures indicate positive returns; red indicates declines.",
        styles["Body"]))
    if "summary" in charts:
        story += add_img(charts["summary"],
                         "Figure 9 — OHLCV Summary (Latest Values)",
                         styles, max_h=10 * cm)

    # ─── Sec 8: Statistics ────────────────────────────────────────────────────
    story.append(PageBreak())
    story += section_banner("8.  Descriptive Statistics", styles)
    if not df.empty:
        extra_cols = [c for c in ["ma5", "ma10", "ma20"] if c in df.columns]
        base_cols  = ["open", "high", "low", "close", "volume", "pct_change_calc", "range"]
        cols       = [c for c in base_cols + extra_cols if c in df.columns]
        desc       = df[cols].describe().round(2).reset_index()
        desc.columns = ["Stat"] + cols
        story.append(df_table(desc, styles))
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            "The table above summarises count, mean, std, min, quartiles, and max for "
            "all numeric columns. MA columns (ma5/ma10/ma20) show fewer rows "
            "(min_periods apply). Large std in volume indicates varied liquidity.",
            styles["Body"]))

    # ─── Sec 9: Data sample ───────────────────────────────────────────────────
    story.append(PageBreak())
    story += section_banner("9.  Cleaned Data Sample  ·  Latest 20 Rows", styles)
    if not df.empty:
        ma_cols = [c for c in ["ma5", "ma10", "ma20"] if c in df.columns]
        show    = [c for c in
                   ["fetched_at", "symbol", "open", "high", "low",
                    "close", "volume", "pct_change_calc", "direction"] + ma_cols
                   if c in df.columns]
        samp = df.sort_values("fetched_at", ascending=False).head(20)[show].copy()
        samp["fetched_at"] = samp["fetched_at"].dt.strftime("%H:%M:%S")
        for c in ("open", "high", "low", "close") + tuple(ma_cols):
            if c in samp:
                samp[c] = samp[c].map(lambda x: f"{float(x):,.2f}" if pd.notna(x) else "—")
        if "volume" in samp:
            samp["volume"] = samp["volume"].map(lambda x: f"{int(x):,}")
        if "pct_change_calc" in samp:
            samp["pct_change_calc"] = samp["pct_change_calc"].map(
                lambda x: f"{'+'if float(x)>=0 else ''}{float(x):.2f}%"
                if str(x).replace('.','').replace('-','').replace('+','').isdigit()
                else x)
        samp.columns = [c.replace("_calc","").replace("_"," ").title()
                        for c in samp.columns]
        story.append(df_table(samp, styles))

    # ─── Footer ───────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.2 * cm))
    story.append(hr(C_BORDER))
    story.append(Paragraph(
        f"NEPSE ETL Pipeline  ·  Report generated "
        f"{datetime.now().strftime('%d %b %Y  %H:%M:%S')} NPT  ·  "
        "Data source: merolagani.com  ·  For informational purposes only.",
        styles["Footer"]))

    doc.build(story)
    log.info(f"PDF report saved: {out_path}")

    return out_path


if __name__ == "__main__":
    from loader import load_cleaned, generate_all_charts
    df     = load_cleaned()
    charts = generate_all_charts(df)
    path   = generate_report(charts, df)
    print(f"Report: {path}")
