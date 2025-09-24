"""
Email sending module using FastAPI Mail.
"""

from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr

from app.core.settings import settings

config = ConnectionConfig(
    MAIL_USERNAME=settings.SMTP_USER,
    MAIL_PASSWORD=settings.SMTP_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.SMTP_PORT,
    MAIL_SERVER=settings.SMTP_HOST,
    MAIL_STARTTLS=settings.SMTP_USE_TLS,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)


async def send_email(
    subject: str,
    email_to: list[str] | list[EmailStr],
    body: str,
    attachments: list[dict[str, str | bytes]] | None = None,
) -> None:
    """
    Email the specified emails address.
    """
    if not email_to:
        raise ValueError("The email_to list cannot be empty.")

    mail_client = FastMail(config)

    message_args = {
        "subject": subject,
        "recipients": email_to,
        "body": body,
        "subtype": MessageType.html,
        "sender": settings.MAIL_FROM,
    }

    if attachments:
        message_args["attachments"] = attachments

    message = MessageSchema(**message_args)

    await mail_client.send_message(message)
