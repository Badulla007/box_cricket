"""Send a real test email using the BOUNDARY .env configuration.
Run: python test_email.py receiver@example.com
"""
import sys
from flask import Flask
from dotenv import load_dotenv
from app import app, email_send, smtp_is_configured

load_dotenv()
if len(sys.argv) != 2:
    raise SystemExit("Usage: python test_email.py recipient@example.com")
recipient = sys.argv[1].strip()
with app.app_context():
    if not smtp_is_configured():
        raise SystemExit("SMTP is not configured. Complete MAIL_USERNAME, MAIL_PASSWORD and MAIL_DEFAULT_SENDER in .env.")
    try:
        email_send(recipient, "BOUNDARY SMTP test", "Your BOUNDARY email configuration can send messages successfully.")
    except Exception as exc:
        raise SystemExit(f"SMTP test failed: {type(exc).__name__}: {exc}")
print(f"SMTP accepted the test message for {recipient}. Check Inbox and Spam.")
