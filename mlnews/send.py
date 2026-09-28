import os
import smtplib
from email.message import EmailMessage


def send_email(subject: str, html: str, text: str) -> None:
    user = os.environ.get("GMAIL_ADDRESS", "")
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    to = [a.strip() for a in os.environ.get("DIGEST_TO", user).split(",") if a.strip()]
    if not (user and pw and to):
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD / DIGEST_TO not set in .env")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"ML News <{user}>", ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)
