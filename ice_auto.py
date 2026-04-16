import os
import requests
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import calendar
import smtplib
from email.message import EmailMessage

# === CONFIG ===
USERNAME = "TrueLight_API"
PASSWORD = "TrueLightEnergy$$$@"
#SAVE_DIR = "/home/ubuntu/ICE_CLEARED_POWER"
SAVE_DIR = os.getenv("SAVE_DIR", os.getenv("GITHUB_WORKSPACE", "."))
# Load environment variables
load_dotenv()

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# === Ensure folder exists ===
os.makedirs(SAVE_DIR, exist_ok=True)

# === Get previous weekday ===
today = date.today()
if today.weekday() >= 5:
    print("Today is Sat/Sun — skipping.")
    exit(0)

date_str = today.strftime("%Y_%m_%d")
print(f"Running for {date_str}")

#file_path = f"Settlement_Reports/Power/icecleared_power_{date_str}.xlsx"
#print(f" Using today's date: {today}, using file path: {file_path}")

# === Authenticate + Download ===
def download_ice_file(username, password, file_path, save_dir):
    try:
        login_info = {
            'userId': username,
            'password': password,
            'appKey': 'ICEDOWNLOADS'
        }
        auth_response = requests.post('https://sso.ice.com/api/authenticateTfa', login_info)
        auth_response.raise_for_status()
        token = auth_response.json()['result']['data']['token']
        cookies = {'iceSsoCookie': token}

        download_url = f'https://downloads.ice.com/{file_path}'
        response = requests.get(download_url, cookies=cookies)
        response.raise_for_status()

        filename = os.path.basename(file_path)
        file_output_path = os.path.join(save_dir, filename)
        with open(file_output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)

        print(f"Downloaded: {file_output_path}")
        return file_output_path

    except Exception as e:
        print(f"Error during download: {e}")
        return None

#downloaded_file = download_ice_file(USERNAME, PASSWORD, file_path, SAVE_DIR)
# === File paths to download ===
paths = [
    f"Settlement_Reports/Power/icecleared_power_{date_str}.xlsx",
    f"Settlement_Reports/Power/ngxcleared_power_{date_str}.xlsx",
    f"Settlement_Reports/Gas/icecleared_gas_{date_str}.xlsx",
    f"Settlement_Reports/Gas/ngxcleared_gas_{date_str}.xlsx"
]

# === Download all ===
attachments = []
for path in paths:
    file = download_ice_file(USERNAME, PASSWORD, path, SAVE_DIR)
    if file:
        attachments.append(file)

# === Send email if any file ===
if attachments:
    try:
        msg = EmailMessage()
        msg['Subject'] = f"ICE/NGX Cleared Power & Gas Reports - {date_str}"
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg.set_content(f"Please find attached ICE & NGX cleared power & gas reports for {date_str}.")

        for fpath in attachments:
            with open(fpath, 'rb') as f:
                msg.add_attachment(
                    f.read(),
                    maintype='application',
                    subtype='octet-stream',
                    filename=os.path.basename(fpath)
                )

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)

        print(f"Email sent to {EMAIL_RECEIVER} with {len(attachments)} attachment(s).")

    except Exception as e:
        print(f" Error sending email: {e}")

else:
    print(" No files downloaded — skipping email.")
