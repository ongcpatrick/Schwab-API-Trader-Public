"""Ephemeral OAuth state and PKCE verifier storage."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class OAuthSession:
    """Single pending OAuth browser flow."""

    state: str
    code_verifier: str
    code_challenge: str
    created_at: datetime


class OAuthSessionStore:
    """In-memory store for short-lived OAuth browser sessions."""

    def __init__(self, *, ttl_minutes: int = 10) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._sessions: dict[str, OAuthSession] = {}
        self._lock = threading.RLock()

    def create(self) -> OAuthSession:
        """Create and persist a new OAuth state + PKCE verifier pair."""

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        session = OAuthSession(
            state=state,
            code_verifier=code_verifier,
            code_challenge=_pkce_s256(code_verifier),
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._prune_locked()
            # Keep a single active browser handoff so stale local sessions
            # cannot interfere with manual code exchange.
            self._sessions.clear()
            self._sessions[state] = session
        return session

    def consume(self, state: str) -> OAuthSession | None:
        """Consume a specific pending OAuth state."""

        with self._lock:
            self._prune_locked()
            return self._sessions.pop(state, None)

    def consume_only_pending(self) -> OAuthSession | None:
        """Consume the sole pending session, if exactly one exists."""

        with self._lock:
            self._prune_locked()
            if len(self._sessions) != 1:
                return None
            only_state = next(iter(self._sessions))
            return self._sessions.pop(only_state)

    def clear(self) -> None:
        """Clear pending sessions."""

        with self._lock:
            self._sessions.clear()

    def _prune_locked(self) -> None:
        cutoff = datetime.now(UTC) - self._ttl
        expired_states = [
            state for state, session in self._sessions.items() if session.created_at < cutoff
        ]
        for state in expired_states:
            self._sessions.pop(state, None)


def _pkce_s256(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


oauth_session_store = OAuthSessionStore()
