"""OAuth configuration helpers."""

from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass(frozen=True)
class OAuthConfig:
    """Configuration for Schwab's authorization-code OAuth flow."""

    client_id: str
    client_secret: str
    redirect_uri: str
    scope: str = "readonly"
    response_type: str = "code"
    authorization_base_url: str = "https://api.schwabapi.com/v1/oauth/authorize"
    token_url: str = "https://api.schwabapi.com/v1/oauth/token"

    def authorization_url(
        self,
        *,
        state: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
    ) -> str:
        """Return a Schwab authorization URL for the configured app."""

        params = {
            "response_type": self.response_type,
            "client_id": self.client_id,
            "scope": self.scope,
            "redirect_uri": self.redirect_uri,
        }
        if state is not None:
            params["state"] = state
        if code_challenge is not None:
            params["code_challenge"] = code_challenge
        if code_challenge_method is not None:
            params["code_challenge_method"] = code_challenge_method
        return f"{self.authorization_base_url}?{urlencode(params)}"
