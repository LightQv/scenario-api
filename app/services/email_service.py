"""
Email service module for sending notification emails.

This module provides functions for sending various types of emails
such as password reset notifications using FastAPI Mail.
"""

from app.core.email import send_email
from app.utils.email_templates import get_password_reset_template


async def send_forgotten_password_email(
    user_email: str, username: str, reset_token: str
) -> None:
    """
    Send password reset email to user.

    Sends a professionally formatted HTML email containing a password reset link
    to the user's registered email address. The email includes the user's username
    and a secure reset token for password recovery.

    Args:
        user_email: Recipient's email address
        username: User's display name for personalization
        reset_token: Unique token for password reset verification

    Returns:
        None

    Raises:
        Exception: If email sending fails due to SMTP issues or invalid configuration

    Example:
        >>> await send_forgotten_password_email(
        ...     user_email="user@example.com",
        ...     username="JohnDoe",
        ...     reset_token="123e4567-e89b-12d3-a456-426614174000"
        ... )
    """
    html_content = get_password_reset_template(username, reset_token)

    await send_email(
        subject=f"{username}, have you forgotten your password?",
        email_to=[user_email],
        body=html_content,
    )
