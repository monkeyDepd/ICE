import os
import sys
import time
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

# === CONFIG ===
ET = ZoneInfo("America/New_York")

# ICE publishes each weekday's settlement reports before 18:00 ET, and this job
# is scheduled at 18:30 ET. So a run that wakes before PUBLISH_CUTOFF_HOUR is a
# delayed run of the *previous* weekday's job, not an on-time run for today.
PUBLISH_CUTOFF_HOUR = 18

# NOTE: unset GitHub secrets arrive as empty strings, not as unset vars, so
# fall back with `or` rather than a getenv default.
ICE_USERNAME = os.getenv("ICE_USERNAME") or "TrueLight_API"
ICE_PASSWORD = os.getenv("ICE_PASSWORD") or "TrueLightEnergy$$$@"

SAVE_DIR = os.getenv("SAVE_DIR", os.getenv("GITHUB_WORKSPACE", "."))

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

AUTH_URL = "https://sso.ice.com/api/authenticateTfa"
DOWNLOAD_HOST = "https://downloads.ice.com"

# An .xlsx is a zip archive. Anything else -- notably the "No Files Available"
# directory listing ICE serves with HTTP 200 -- must not be emailed as a report.
XLSX_MAGIC = b"PK\x03\x04"

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 60


def target_report_date(now_et):
    """Which report date this run is responsible for.

    Uses ET rather than the runner's UTC clock, and rolls back when the run
    starts too early to be on time (GitHub's scheduler has delayed this job by
    as much as 8 hours). Rolls back to the previous *weekday* so a Friday job
    that slips into the weekend still fetches Friday.
    """
    report_date = now_et.date()
    if now_et.hour < PUBLISH_CUTOFF_HOUR:
        report_date -= timedelta(days=1)
    while report_date.weekday() >= 5:
        report_date -= timedelta(days=1)
    return report_date


def get_ice_token():
    response = requests.post(
        AUTH_URL,
        {"userId": ICE_USERNAME, "password": ICE_PASSWORD, "appKey": "ICEDOWNLOADS"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["result"]["data"]["token"]


def fetch_report(file_path):
    """Return the report bytes, or None if ICE did not serve a real workbook."""
    token = get_ice_token()
    response = requests.get(
        f"{DOWNLOAD_HOST}/{file_path}",
        cookies={"iceSsoCookie": token},
        timeout=300,
    )
    response.raise_for_status()

    body = response.content
    if not body.startswith(XLSX_MAGIC):
        preview = body[:120].decode("utf-8", errors="replace").replace("\n", " ")
        raise ValueError(f"not an xlsx ({len(body)} bytes): {preview}")
    return body


def download_report(file_path, save_dir):
    filename = os.path.basename(file_path)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            body = fetch_report(file_path)
        except Exception as e:
            print(f"{filename}: attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)
            continue

        output_path = os.path.join(save_dir, filename)
        with open(output_path, "wb") as f:
            f.write(body)
        print(f"Downloaded: {output_path} ({len(body)} bytes)")
        return output_path

    print(f"Giving up on {filename}")
    return None


def send_email(report_date_str, attachments, missing):
    subject = f"ICE/NGX Cleared Power & Gas Reports - {report_date_str}"
    if missing:
        subject += f" (PARTIAL - {len(missing)} missing)"

    lines = [f"ICE & NGX cleared power & gas reports for {report_date_str}."]
    if missing:
        lines.append("")
        lines.append("Not available at run time:")
        lines.extend(f"  - {name}" for name in missing)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.set_content("\n".join(lines))

    for path in attachments:
        with open(path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=os.path.basename(path),
            )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
        smtp.send_message(msg)

    print(f"Email sent to {EMAIL_RECEIVER} with {len(attachments)} attachment(s).")


def main():
    now_et = datetime.now(ET)
    report_date = target_report_date(now_et)
    date_str = report_date.strftime("%Y_%m_%d")

    print(f"Now (ET): {now_et:%Y-%m-%d %H:%M:%S %Z}")
    print(f"Target report date: {date_str} ({report_date:%A})")

    os.makedirs(SAVE_DIR, exist_ok=True)

    paths = [
        f"Settlement_Reports/Power/icecleared_power_{date_str}.xlsx",
        f"Settlement_Reports/Power/ngxcleared_power_{date_str}.xlsx",
        f"Settlement_Reports/Gas/icecleared_gas_{date_str}.xlsx",
        f"Settlement_Reports/Gas/ngxcleared_gas_{date_str}.xlsx",
    ]

    attachments = []
    missing = []
    for path in paths:
        downloaded = download_report(path, SAVE_DIR)
        if downloaded:
            attachments.append(downloaded)
        else:
            missing.append(os.path.basename(path))

    if not attachments:
        print("No valid reports downloaded - skipping email.")
        return 1

    try:
        send_email(date_str, attachments, missing)
    except Exception as e:
        print(f"Error sending email: {e}")
        return 1

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
