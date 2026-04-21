"""Local token persistence."""

import os
from pathlib import Path

from schwab_trader.auth.models import OAuthToken


class FileTokenStore:
    """Persist OAuth tokens to a local JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> OAuthToken | None:
        """Load the stored token, if present."""

        if not self.path.exists():
            return None
        return OAuthToken.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, token: OAuthToken) -> None:
        """Persist the current token and restrict file permissions."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(token.model_dump_json(indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except PermissionError:
            pass

    def clear(self) -> None:
        """Remove any stored token."""

        if self.path.exists():
            self.path.unlink()
