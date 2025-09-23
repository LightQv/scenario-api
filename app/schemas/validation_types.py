"""
Validation type.
"""

import re
from typing import Annotated

from pydantic import BeforeValidator

from app.core.exceptions.custom_exception import CustomExceptionError
from app.services.constant.response_constant import (
    PASSWORD_MISSING_LOWER_CASE_ERROR,
    PASSWORD_MISSING_UPPERCASE_ERROR,
    PASSWORD_MISSING_DIGIT_ERROR,
    PASSWORD_MISSING_SPECIAL_CHARACTER_ERROR,
    INVALID_EMAIL_ERROR,
)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def email_is_valid(email: str) -> str:
    """
    Validate the email address.
    :param email: Email address to validate.
    :return: The stripped email address if valid.
    :raises CustomExceptionError: If the email is invalid.
    """
    email = email.strip()

    if not EMAIL_REGEX.match(email):
        raise CustomExceptionError(INVALID_EMAIL_ERROR)

    return email


def password_is_valid(password: str) -> str:
    """
    Validate the password.
    Args:
        password:

    Returns:
        ValueError or password
    """
    if not any(char.isdigit() for char in password):
        raise CustomExceptionError(PASSWORD_MISSING_DIGIT_ERROR)
    if not any(char.isupper() for char in password):
        raise CustomExceptionError(PASSWORD_MISSING_UPPERCASE_ERROR)
    if not any(char.islower() for char in password):
        raise CustomExceptionError(PASSWORD_MISSING_LOWER_CASE_ERROR)
    if not any(char in "!@#$%^&*()-+" for char in password):
        raise CustomExceptionError(PASSWORD_MISSING_SPECIAL_CHARACTER_ERROR)
    return password


ValidEmail = Annotated[str, BeforeValidator(email_is_valid)]
ValidPassword = Annotated[str, BeforeValidator(password_is_valid)]
