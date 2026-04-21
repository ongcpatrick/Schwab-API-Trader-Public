"""Ephemeral OAuth state and PKCE verifier storage — file-backed for Railway."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class OAuthSession:
    """Single pending OAuth browser flow."""

    state: str
    code_verifier: str
    code_challenge: str
    created_at: datetime


class OAuthSessionStore:
    """File-backed store for short-lived OAuth browser sessions.

    Persists the PKCE session to disk so that Railway container restarts
    between the auth redirect and the callback do not lose the verifier.
    """

    def __init__(self, *, ttl_minutes: int = 15, path: Path | None = None) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._path = path or Path(os.getenv("SCHWAB_SESSION_PATH", ".data/oauth_session.json"))
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
            self._write(session)
        return session

    def consume(self, state: str) -> OAuthSession | None:
        """Consume a specific pending OAuth state."""

        with self._lock:
            session = self._read()
            if session is None or session.state != state:
                return None
            if self._is_expired(session):
                self._delete()
                return None
            self._delete()
            return session

    def consume_only_pending(self) -> OAuthSession | None:
        """Consume the sole pending session, if one exists and is not expired."""

        with self._lock:
            session = self._read()
            if session is None or self._is_expired(session):
                self._delete()
                return None
            self._delete()
            return session

    def clear(self) -> None:
        """Clear any pending session."""

        with self._lock:
            self._delete()

    # ------------------------------------------------------------------
    # Internal helpers

    def _write(self, session: OAuthSession) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "state": session.state,
            "code_verifier": session.code_verifier,
            "code_challenge": session.code_challenge,
            "created_at": session.created_at.isoformat(),
        }
        self._path.write_text(json.dumps(data))

    def _read(self) -> OAuthSession | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
            return OAuthSession(
                state=data["state"],
                code_verifier=data["code_verifier"],
                code_challenge=data["code_challenge"],
                created_at=datetime.fromisoformat(data["created_at"]),
            )
        except Exception:
            return None

    def _delete(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except Exception:
            pass

    def _is_expired(self, session: OAuthSession) -> bool:
        ts = session.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return datetime.now(UTC) - ts > self._ttl


def _pkce_s256(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


oauth_session_store = OAuthSessionStore()
