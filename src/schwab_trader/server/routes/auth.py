"""OAuth routes."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from schwab_trader.auth.models import OAuthToken
from schwab_trader.auth.service import SchwabOAuthService
from schwab_trader.auth.session_store import OAuthSessionStore
from schwab_trader.auth.token_store import FileTokenStore
from schwab_trader.server.dependencies import (
    get_oauth_service,
    get_oauth_session_store,
    get_token_store,
)


class AuthorizationUrlResponse(BaseModel):
    """Authorization URL payload."""

    authorization_url: str


class ExchangeCodeRequest(BaseModel):
    """Manual authorization-code exchange payload."""

    code: str
    session: str | None = None
    state: str | None = None


class AuthCallbackResponse(BaseModel):
    """OAuth callback exchange response."""

    message: str
    session: str | None = None


class AuthStatusResponse(BaseModel):
    """Current local auth status."""

    authenticated: bool
    access_token_expires_at: str | None = None


router = APIRouter()


def _raise_for_schwab_error(exc: httpx.HTTPStatusError) -> None:
    detail: object
    try:
        detail = exc.response.json()
    except ValueError:
        detail = exc.response.text or "Schwab OAuth request failed."
    raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc


def _exchange_and_store_token(
    *,
    code: str,
    code_verifier: str | None,
    oauth_service: SchwabOAuthService,
    token_store: FileTokenStore,
) -> None:
    try:
        token: OAuthToken = oauth_service.exchange_authorization_code(
            code,
            code_verifier=code_verifier,
        )
    except httpx.HTTPStatusError as exc:
        _raise_for_schwab_error(exc)
    token_store.save(token)


def _consume_oauth_session(
    *,
    state: str | None,
    session_store: OAuthSessionStore,
) -> tuple[str, str]:
    if state is not None:
        session = session_store.consume(state)
    else:
        session = session_store.consume_only_pending()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state.",
        )
    return session.state, session.code_verifier


@router.get("/api/v1/auth/authorize-url", response_model=AuthorizationUrlResponse)
def authorize_url(
    oauth_service: Annotated[SchwabOAuthService, Depends(get_oauth_service)],
    session_store: Annotated[OAuthSessionStore, Depends(get_oauth_session_store)],
) -> AuthorizationUrlResponse:
    """Return the Schwab authorization URL for the configured app."""

    session = session_store.create()
    return AuthorizationUrlResponse(
        authorization_url=oauth_service.authorization_url(
            state=session.state,
            code_challenge=session.code_challenge,
            code_challenge_method="S256",
        )
    )


@router.get("/auth/start")
def auth_start(
    oauth_service: Annotated[SchwabOAuthService, Depends(get_oauth_service)],
    session_store: Annotated[OAuthSessionStore, Depends(get_oauth_session_store)],
) -> RedirectResponse:
    """Redirect the browser to the configured Schwab OAuth URL."""

    session = session_store.create()
    return RedirectResponse(
        url=oauth_service.authorization_url(
            state=session.state,
            code_challenge=session.code_challenge,
            code_challenge_method="S256",
        ),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.post("/api/v1/auth/exchange-code", response_model=AuthCallbackResponse)
def exchange_code(
    payload: Annotated[ExchangeCodeRequest, Body()],
    oauth_service: Annotated[SchwabOAuthService, Depends(get_oauth_service)],
    session_store: Annotated[OAuthSessionStore, Depends(get_oauth_session_store)],
    token_store: Annotated[FileTokenStore, Depends(get_token_store)],
) -> AuthCallbackResponse:
    """Exchange a manually supplied Schwab authorization code."""

    _, code_verifier = _consume_oauth_session(state=payload.state, session_store=session_store)
    _exchange_and_store_token(
        code=payload.code,
        code_verifier=code_verifier,
        oauth_service=oauth_service,
        token_store=token_store,
    )
    return AuthCallbackResponse(
        message="Schwab authorization completed.",
        session=payload.session,
    )


@router.get("/auth/callback")
def auth_callback(
    code: Annotated[str | None, Query()] = None,
    session: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    error_description: Annotated[str | None, Query()] = None,
    oauth_service: Annotated[SchwabOAuthService, Depends(get_oauth_service)] = ...,
    session_store: Annotated[OAuthSessionStore, Depends(get_oauth_session_store)] = ...,
    token_store: Annotated[FileTokenStore, Depends(get_token_store)] = ...,
) -> RedirectResponse:
    """Handle the Schwab OAuth callback, exchange the code, and redirect to dashboard."""

    if error is not None:
        detail = error_description or error
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth authorization code.",
        )
    _, code_verifier = _consume_oauth_session(state=state, session_store=session_store)
    _exchange_and_store_token(
        code=code,
        code_verifier=code_verifier,
        oauth_service=oauth_service,
        token_store=token_store,
    )
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)


@router.get("/api/v1/auth/status", response_model=AuthStatusResponse)
def auth_status(
    token_store: Annotated[FileTokenStore, Depends(get_token_store)],
) -> AuthStatusResponse:
    """Return whether a local Schwab token is present."""

    token = token_store.load()
    return AuthStatusResponse(
        authenticated=token is not None,
        access_token_expires_at=token.access_token_expires_at.isoformat() if token else None,
    )
