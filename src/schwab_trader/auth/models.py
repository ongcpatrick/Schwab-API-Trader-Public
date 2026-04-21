"""OAuth token models."""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field


class OAuthToken(BaseModel):
    """Stored OAuth token set."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    scope: str | None = None
    expires_in: int = 1800
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def access_token_expires_at(self) -> datetime:
        """Return the access-token expiry timestamp."""

        return self.created_at + timedelta(seconds=self.expires_in)

    def is_access_token_expired(self, *, leeway_seconds: int = 30) -> bool:
        """Return whether the access token should be treated as expired."""

        cutoff = self.access_token_expires_at - timedelta(seconds=leeway_seconds)
        return datetime.now(UTC) >= cutoff
