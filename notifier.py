"""
notifier.py  ─  Desktop notifications + Email (Linux only)

Notifications: notify-send with "Open PDF" button → opens in Brave.
               Falls back to zenity dialog if notify-send is missing.
Email:         Gmail SMTP/TLS with HTML + PDF attachment.

Setup (one-time):
    export NEPSE_EMAIL_SENDER=you@gmail.com
    export NEPSE_EMAIL_PASSWORD=xxxx_xxxx_xxxx_xxxx   # Gmail App Password
    export NEPSE_EMAIL_RECIPIENTS=a@gmail.com,b@gmail.com
    export NEPSE_EMAIL_ENABLED=true
"""

import ssl, smtplib, socket, subprocess, threading
from datetime import datetime
from pathlib import Path
from email.mime.multipart   import MIMEMultipart
from email.mime.text        import MIMEText
from email.mime.application import MIMEApplication

from config import (
    EMAIL_ENABLED, EMAIL_SENDER, EMAIL_PASSWORD,
    EMAIL_RECIPIENTS, EMAIL_CC,
    EMAIL_SMTP_HOST, EMAIL_SMTP_PORT,
    EMAIL_SUBJECT_TPL, NPT,
)
from logger import get_logger

log = get_logger("notifier")


# ── Desktop notification ───────────────────────────────────────────────────────

def _open_in_brave(pdf_path: str):
    """Open the PDF in Brave browser. Never raises."""
    try:
        subprocess.Popen(["brave-browser", f"file://{pdf_path}"])
    except Exception as e:
        log.debug(f"Could not open PDF in Brave: {e}")


def notify(title: str, body: str, pdf_path: str | Path | None = None):
    """
    Send a desktop notification with an 'Open PDF' button.
    Clicking the button opens the PDF in Brave browser.
    Never raises.
    """
    pdf_path = str(pdf_path) if isinstance(pdf_path, Path) else pdf_path
    try:
        if pdf_path:
            # notify-send >= 0.7.9: --action adds a clickable button
            # Blocks until dismissed; stdout is "open" if button was clicked
            result = subprocess.run(
                ["notify-send", title, body,
                 "--icon=dialog-information",
                 "--expire-time=15000",
                 "--action=open:Open PDF",
                 "--wait"],
                timeout=20,
                )

            if result.returncode == 0 and pdf_path:
                subprocess.Popen(["xdg-open", str(pdf_path)])

        else:
            subprocess.run(
                ["notify-send", title, body,
                 "--icon=dialog-information", "--expire-time=15000"],
                timeout=5, capture_output=True,
            )
        log.info("Desktop notification sent.")

    except FileNotFoundError:
        # notify-send not installed — fall back to zenity
        try:
            result = subprocess.run(
                ["zenity", "--question",
                 f"--title={title}",
                 f"--text={body}\n\nClick OK to open the PDF.",
                 "--ok-label=Open PDF", "--cancel-label=Dismiss",
                 "--timeout=20"],
                timeout=25, capture_output=True,
            )
            if result.returncode == 0 and pdf_path:
                _open_in_brave(pdf_path)
        except FileNotFoundError:
            log.info("No notification tool found — install: sudo apt install libnotify-bin")
    except Exception as e:
        log.debug(f"notify() error: {e}")


def notify_async(title: str, body: str, pdf_path: str | Path | None = None):
    """Fire-and-forget notification in a daemon thread."""
    threading.Thread(target=notify, args=(title, body, pdf_path), daemon=True).start()


# ── Email ──────────────────────────────────────────────────────────────────────

def _html_body(pdf_path: Path, summary: dict | None) -> str:
    today    = datetime.now(NPT).strftime("%A, %d %B %Y")
    gen_time = datetime.now(NPT).strftime("%H:%M NPT")
    size     = f"{pdf_path.stat().st_size/1024:.1f} KB" if pdf_path.exists() else "—"

    kpi_rows = ""
    if summary:
        for label, value in [
            ("Symbols Tracked",  str(summary.get("n_symbols", "—"))),
            ("Total Volume",     f"{summary.get('total_volume', 0):,}"),
            ("Gainers / Losers", f"{summary.get('gainers','—')} / {summary.get('losers','—')}"),
            ("Avg % Change",     f"{summary.get('avg_change', 0.0):+.2f}%"),
        ]:
            kpi_rows += (
                f'<tr><td style="padding:9px 18px;color:#555;font-size:13px;'
                f'border-bottom:1px solid #e8ecf0;">{label}</td>'
                f'<td style="padding:9px 18px;font-weight:600;color:#1A3A5C;font-size:13px;'
                f'text-align:right;border-bottom:1px solid #e8ecf0;">{value}</td></tr>'
            )

    kpi_block = f"""
    <h3 style="color:#1565C0;font-size:14px;margin:28px 0 8px;">Session Highlights</h3>
    <table width="100%" style="border:1px solid #D6E4F0;border-radius:6px;
           border-collapse:collapse;background:#F8FBFF;">
      <thead><tr style="background:#1565C0;">
        <th style="padding:10px 18px;color:white;font-size:12px;text-align:left;">Metric</th>
        <th style="padding:10px 18px;color:white;font-size:12px;text-align:right;">Value</th>
      </tr></thead>
      <tbody>{kpi_rows}</tbody>
    </table>""" if kpi_rows else ""

    return f"""<!DOCTYPE html><html><body style="margin:0;background:#F0F4F8;
font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" style="padding:32px 16px;"><tr><td align="center">
<table width="600" style="background:#fff;border-radius:10px;
       box-shadow:0 2px 12px rgba(0,0,0,.1);overflow:hidden;">
  <tr><td style="background:linear-gradient(135deg,#0d1b2a,#1565c0);padding:28px 32px;">
    <h2 style="margin:0;color:#29b6f6;font-size:22px;">&#128200; NEPSE Daily Market Report</h2>
    <p style="margin:6px 0 0;color:#90caf9;font-size:13px;">{today} &middot; Generated {gen_time}</p>
  </td></tr>
  <tr><td style="padding:28px 32px;">
    <p style="color:#333;font-size:14px;line-height:1.7;margin:0 0 20px;">
      Your NEPSE daily market report is ready and attached as a PDF.</p>
    {kpi_block}
    <table width="100%" style="margin-top:24px;border:1px solid #E0E7EF;
           border-radius:8px;background:#F8FBFF;">
      <tr>
        <td style="padding:14px 16px;font-size:22px;width:44px;">&#128206;</td>
        <td style="padding:14px 8px;">
          <p style="margin:0;color:#1A1A2E;font-size:13px;font-weight:600;">{pdf_path.name}</p>
          <p style="margin:3px 0 0;color:#888;font-size:12px;">PDF &middot; {size}</p>
        </td>
      </tr>
    </table>
  </td></tr>
  <tr><td style="background:#F4F6FA;padding:16px 32px;border-top:1px solid #E8ECF4;">
    <p style="margin:0;color:#999;font-size:11px;text-align:center;">
      Data: merolagani.com &middot; NEPSE ETL Pipeline &middot; Informational use only.</p>
  </td></tr>
</table></td></tr></table></body></html>"""


def _plain_body(pdf_path: Path, summary: dict | None) -> str:
    lines = [
        "NEPSE ETL Analytics Report", "=" * 40,
        f"Generated : {datetime.now(NPT).strftime('%A, %d %B %Y  %H:%M NPT')}",
        f"Attachment: {pdf_path.name}", "",
    ]
    if summary:
        lines += [
            "Session Highlights", "-" * 22,
            f"  Symbols  : {summary.get('n_symbols','—')}",
            f"  Volume   : {summary.get('total_volume',0):,}",
            f"  G/L      : {summary.get('gainers','—')} / {summary.get('losers','—')}",
            f"  Avg Chg  : {summary.get('avg_change',0.0):+.2f}%", "",
        ]
    lines += ["See attached PDF for the full report.",
              "—", "NEPSE ETL Pipeline | merolagani.com | Informational use only."]
    return "\n".join(lines)


def send_report(
    pdf_path: Path,
    recipients: list[str] | None = None,
    cc: list[str] | None = None,
    summary: dict | None = None,
) -> bool:
    """Send PDF report via Gmail SMTP. Returns True on success."""
    if not EMAIL_ENABLED:
        log.info("Email disabled (NEPSE_EMAIL_ENABLED=false).")
        return False
    if not pdf_path.exists():
        log.error(f"PDF not found: {pdf_path}")
        return False

    to_list = recipients or EMAIL_RECIPIENTS
    cc_list = cc         or EMAIL_CC
    if not to_list:
        log.warning("No recipients. Set NEPSE_EMAIL_RECIPIENTS.")
        return False

    subject = EMAIL_SUBJECT_TPL.format(date=datetime.now(NPT).strftime("%d %b %Y"))
    msg = MIMEMultipart("mixed")
    msg["From"]    = f"NEPSE ETL Pipeline <{EMAIL_SENDER}>"
    msg["To"]      = ", ".join(to_list)
    msg["Subject"] = subject
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(_plain_body(pdf_path, summary), "plain"))
    alt.attach(MIMEText(_html_body(pdf_path,  summary), "html"))
    msg.attach(alt)

    part = MIMEApplication(pdf_path.read_bytes(), _subtype="pdf")
    part.add_header("Content-Disposition", "attachment", filename=pdf_path.name)
    msg.attach(part)

    try:
        log.info(f"Sending email to {', '.join(to_list)} …")
        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=30) as s:
            s.ehlo(); s.starttls(context=ssl.create_default_context()); s.ehlo()
            s.login(EMAIL_SENDER, EMAIL_PASSWORD)
            s.sendmail(EMAIL_SENDER, to_list + cc_list, msg.as_string())
        log.info("Email sent.")
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("Auth failed — use a Gmail App Password, not your main password.")
    except smtplib.SMTPRecipientsRefused as e:
        log.error(f"Recipients refused: {e}")
    except (smtplib.SMTPConnectError, socket.timeout) as e:
        log.error(f"Connection error: {e}")
    except Exception as e:
        log.error(f"Email failed: {e}", exc_info=True)
    return False


# ── CLI test ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2:
        ok = send_report(Path(sys.argv[1]), recipients=sys.argv[2:] or None)
        sys.exit(0 if ok else 1)
    else:
        notify("NEPSE ETL — Test", "Desktop notifications are working!")
        print("Notification fired. Check your desktop.")