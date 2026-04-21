"""Schwab OAuth token-exchange service."""

from base64 import b64encode
from collections.abc import Mapping

import httpx

from schwab_trader.auth.models import OAuthToken
from schwab_trader.auth.oauth import OAuthConfig


class SchwabOAuthService:
    """Perform Schwab OAuth exchanges and refreshes."""

    def __init__(
        self,
        *,
        config: OAuthConfig,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def authorization_url(
        self,
        *,
        state: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
    ) -> str:
        """Return the configured Schwab authorization URL."""

        return self.config.authorization_url(
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

    def exchange_authorization_code(
        self,
        code: str,
        *,
        code_verifier: str | None = None,
    ) -> OAuthToken:
        """Exchange an authorization code for an access token."""

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
        }
        if code_verifier is not None:
            payload["code_verifier"] = code_verifier
        data = self._post_token(payload)
        return OAuthToken.model_validate(data)

    def refresh_access_token(self, refresh_token: str) -> OAuthToken:
        """Refresh the access token using the stored refresh token."""

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        data = self._post_token(payload)
        if "refresh_token" not in data:
            data["refresh_token"] = refresh_token
        return OAuthToken.model_validate(data)

    def _post_token(self, payload: Mapping[str, str]) -> dict:
        """Post form-encoded token requests to Schwab."""

        response = self._client.post(
            self.config.token_url,
            data=dict(payload),
            headers={
                "Authorization": self._authorization_header(),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()

    def _authorization_header(self) -> str:
        credentials = f"{self.config.client_id}:{self.config.client_secret}".encode()
        return f"Basic {b64encode(credentials).decode('utf-8')}"
