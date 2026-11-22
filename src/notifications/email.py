import smtplib
from email.message import EmailMessage

from src.config import Settings


def send_email(settings: Settings, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.EMAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=10) as smtp:
        smtp.send_message(message)
