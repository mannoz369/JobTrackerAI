from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GmailWatchState(BaseModel):
    status: Literal["not_registered", "registered", "expired"] = "not_registered"
    history_id: str | None = None
    expiration: datetime | None = None
    topic_name: str | None = None
    last_registered_at: datetime | None = None


class OAuthTokenMetadata(BaseModel):
    refresh_token_encrypted: str | None = None
    access_token_expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    token_type: str | None = None
    last_refreshed_at: datetime | None = None


class GoogleUserProfile(BaseModel):
    google_sub: str
    email: str
    email_verified: bool = False
    name: str | None = None
    picture: str | None = None


class UserRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    google_sub: str
    email: str
    email_verified: bool = False
    monitored_email: str
    name: str | None = None
    picture: str | None = None
    oauth: OAuthTokenMetadata
    gmail_watch: GmailWatchState = Field(default_factory=GmailWatchState)
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def stringify_mongo_id(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value)
