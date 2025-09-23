from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.settings import settings
from app.schemas.validation_types import ValidEmail, ValidPassword


class UserRegister(BaseModel):
    username: str = Field(
        ...,
        min_length=settings.USERNAME_MIN_LENGTH,
        max_length=settings.USERNAME_MAX_LENGTH,
    )
    email: ValidEmail = Field(..., max_length=255)
    password: ValidPassword = Field(
        ...,
        min_length=settings.PASSWORD_MIN_LENGTH,
        max_length=settings.PASSWORD_MAX_LENGTH,
    )
    confirm_password: ValidPassword

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, value, info) -> str:
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("Les mots de passe ne correspondent pas")
        return value


class UserLogin(BaseModel):
    email: ValidEmail
    password: str


class PasswordReset(BaseModel):
    password: ValidPassword = Field(
        ...,
        min_length=settings.PASSWORD_MIN_LENGTH,
        max_length=settings.PASSWORD_MAX_LENGTH,
    )
    confirm_password: ValidPassword
    password_token: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, value, info) -> str:
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("Les mots de passe ne correspondent pas")
        return value


class ForgottenPassword(BaseModel):
    email: EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str
