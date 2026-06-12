import smtplib
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

KEY_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'api_keys.json'))

def _load_email_config():
    try:
        with open(KEY_FILE) as f:
            keys = json.load(f)
        cfg = keys.get('email', {})
        return cfg.get('gmail_address', ''), cfg.get('gmail_app_password', ''), cfg.get('admin_email', '')
    except Exception:
        return '', '', ''

def send_email(subject, body, to=None):
    sender, app_password, admin_email = _load_email_config()
    recipient = to or admin_email
    if not sender or not app_password or not recipient:
        raise ValueError("Email nije konfiguriran u Settings.")
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient
    msg.attach(MIMEText(body, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(sender, app_password)
        server.sendmail(sender, recipient, msg.as_string())

def is_configured():
    sender, app_password, admin_email = _load_email_config()
    return bool(sender and app_password and admin_email)
