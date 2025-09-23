import time
from pydantic import BaseModel, field_validator, Field, ConfigDict, model_validator
from typing import Optional
from uuid import UUID

from app.schemas.validation_types import ValidPassword, ValidEmail


class UserBase(BaseModel):
    username: str = Field(..., min_length=5, max_length=100)
    email: ValidEmail = Field(..., max_length=255)


class UserCreate(UserBase):
    password: str = Field(..., min_length=7, max_length=30)


class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=5, max_length=100)
    email: Optional[ValidEmail] = Field(None, max_length=255)
    password: Optional[ValidPassword] = Field(None, min_length=7, max_length=30)


class UserUpdateEmail(BaseModel):
    email: ValidEmail = Field(..., max_length=255)


class UserUpdatePassword(BaseModel):
    password: ValidPassword = Field(..., min_length=7, max_length=30)
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, value, info):
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("Les mots de passe ne correspondent pas")
        return value


class UserUpdateBanner(BaseModel):
    banner_link: str


class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    profile_banner: Optional[str] = None

    @model_validator(mode="after")
    def generate_banner_url(self):
        """
        Generate the full banner URL from the filename stored in database.

        If the user has a profile_banner filename, converts it to the full URL
        that can be used by frontend applications to access the banner image.
        """
        if self.profile_banner:
            timestamp: int = int(time.time())
            self.profile_banner = f"/api/v1/uploads/banner/{self.id}?t={timestamp}"
        return self

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, str_strip_whitespace=True
    )


class UserPublic(BaseModel):
    id: UUID
    username: str
    email: str
    profile_banner: Optional[str] = None

    @model_validator(mode="after")
    def generate_banner_url(self):
        """
        Generate the full banner URL from the filename stored in database.

        If the user has a profile_banner filename, converts it to the full URL
        that can be used by frontend applications to access the banner image.
        This ensures consistency across all API responses.
        """
        if self.profile_banner:
            if hasattr(self, "updated_at") and self.updated_at:
                from datetime import datetime

                if isinstance(self.updated_at, str):
                    date: datetime = datetime.fromisoformat(
                        self.updated_at.replace("Z", "+00:00")
                    )
                    timestamp = int(date.timestamp())
                else:
                    timestamp = int(self.updated_at.timestamp())
                timestamp = int(time.time())
            else:
                timestamp = int(time.time())

            self.profile_banner = f"/api/v1/uploads/banner/{self.id}?t={timestamp}"
        return self

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, str_strip_whitespace=True
    )


class UserBanner(BaseModel):
    profile_banner: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, str_strip_whitespace=True
    )
