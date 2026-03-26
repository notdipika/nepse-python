"""
notifier.py  ─  Desktop notifications + Email (Linux only)

Notifications: notify-send with "Open PDF" button → opens in Brave.
               Falls back to zenity dialog if notify-send is missing.
Email:         Gmail SMTP/TLS with HTML + PDF attachment.

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
    today = datetime.now(NPT).strftime("%A, %d %B %Y")
    gen_time = datetime.now(NPT).strftime("%H:%M NPT")

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;background:#F0F4F8;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" style="padding:32px 16px;">
    <tr><td align="center">
      <table width="600" style="background:#fff;border-radius:10px;
             box-shadow:0 2px 12px rgba(0,0,0,.1);overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background:#1565c0;padding:24px 32px;">
            <h2 style="margin:0;color:#fff;font-size:20px;">
              NEPSE Daily Report
            </h2>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px;text-align:center;">
            <p style="font-size:16px;color:#333;margin:0 0 10px;">
              📄 Your report for
            </p>

            <p style="font-size:20px;font-weight:600;color:#1565c0;margin:0;">
              {today}
            </p>

            <p style="font-size:14px;color:#666;margin-top:20px;">
              Generated at {gen_time}
            </p>

            <p style="margin-top:25px;font-size:15px;color:#333;">
              The report is attached as a PDF.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

def _plain_body(pdf_path: Path, summary: dict | None) -> str:
    today = datetime.now(NPT).strftime("%A, %d %B %Y")
    gen_time = datetime.now(NPT).strftime("%H:%M NPT")

    return "\n".join([
        "NEPSE Daily Market Report",
        "=" * 35,
        "",
        f"Report Date : {today}",
        f"Generated   : {gen_time}",
        "",
        "Today's NEPSE report is attached as a PDF.",
        "",
        f"Attachment  : {pdf_path.name}",
        "",
        "—",
        "NEPSE ETL Pipeline | merolagani.com | Informational use only."
    ])


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
        log.info(f"Connecting to SMTP server {EMAIL_SMTP_HOST}:{EMAIL_SMTP_PORT} …")
        log.info(f"Sending email to {', '.join(to_list + cc_list)} …")

        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=60) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())  # STARTTLS
            s.ehlo()
            s.login(EMAIL_SENDER, EMAIL_PASSWORD)
            s.sendmail(EMAIL_SENDER, to_list + cc_list, msg.as_string())

        log.info("Email sent successfully.")
        return True

    except smtplib.SMTPAuthenticationError:
        log.error("Auth failed — use correct credentials or App Password.")
    except smtplib.SMTPRecipientsRefused as e:
        log.error(f"Recipients refused: {e}")
    except (smtplib.SMTPConnectError, socket.timeout, smtplib.SMTPServerDisconnected) as e:
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

        