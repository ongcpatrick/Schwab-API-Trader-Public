"""Simple JSON-backed alert store."""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parents[4] / ".alerts.json"
_DATA_DIR = Path(__file__).resolve().parents[4] / ".data"


class AlertStore:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.RLock()

    def load_all(self) -> list[dict]:
        with self._lock:
            return self._read_alerts_unlocked()

    def save_alert(self, alert: dict) -> None:
        with self._lock:
            alerts = self._read_alerts_unlocked()
            alerts.insert(0, alert)
            self._write_alerts_unlocked(alerts[:100])

    def update_status(self, alert_id: str, status: str) -> bool:
        with self._lock:
            alerts = self._read_alerts_unlocked()
            for alert in alerts:
                if alert["id"] == alert_id:
                    alert["status"] = status
                    self._write_alerts_unlocked(alerts)
                    return True
            return False

    def mark_sms_sent(self, alert_id: str) -> None:
        with self._lock:
            alerts = self._read_alerts_unlocked()
            for alert in alerts:
                if alert["id"] == alert_id:
                    alert["sms_sent"] = True
                    self._write_alerts_unlocked(alerts)
                    return

    def mark_email_sent(self, alert_id: str) -> None:
        """Mark an alert as having sent its email notification."""

        with self._lock:
            alerts = self._read_alerts_unlocked()
            for alert in alerts:
                if alert["id"] == alert_id:
                    alert["email_sent"] = True
                    self._write_alerts_unlocked(alerts)
                    return

    def get_pending(self) -> list[dict]:
        return [a for a in self.load_all() if a.get("status") == "pending"]

    def get_pending_buy_symbols(self) -> set[str]:
        """Return symbols that already have a pending BUY proposal (avoid duplicates)."""
        symbols: set[str] = set()
        for alert in self.load_all():
            for p in alert.get("proposals", []):
                if p.get("action") == "BUY" and p.get("status") == "pending":
                    symbols.add(p["symbol"])
        return symbols

    def find_proposal_by_token(self, token: str) -> tuple[dict | None, dict | None]:
        """Return (proposal, parent_alert) matching an approval or denial token."""
        with self._lock:
            return self._find_proposal_by_token_unlocked(token)

    def find_proposal_by_id(self, proposal_id: str) -> tuple[dict | None, dict | None]:
        """Return (proposal, parent_alert) for a proposal id."""

        with self._lock:
            alerts = self._read_alerts_unlocked()
            for alert in alerts:
                for proposal in alert.get("proposals", []):
                    if proposal.get("id") == proposal_id:
                        return proposal, alert
            return None, None

    def update_proposal_status(self, proposal_id: str, status: str) -> bool:
        """Persist a status change on a single proposal across all alerts."""
        with self._lock:
            alerts = self._read_alerts_unlocked()
            for alert in alerts:
                for proposal in alert.get("proposals", []):
                    if proposal["id"] == proposal_id:
                        proposal["status"] = status
                        self._write_alerts_unlocked(alerts)
                        return True
            return False

    def issue_confirmation_token(self, proposal_id: str, *, ttl_minutes: int = 10) -> str | None:
        """Attach a short-lived confirmation token to a proposal."""

        token = secrets.token_urlsafe(24)
        expires_at = (datetime.now(UTC) + timedelta(minutes=ttl_minutes)).isoformat()
        with self._lock:
            alerts = self._read_alerts_unlocked()
            for alert in alerts:
                for proposal in alert.get("proposals", []):
                    if proposal["id"] == proposal_id:
                        proposal["confirmation_token"] = token
                        proposal["confirmation_token_expires_at"] = expires_at
                        self._write_alerts_unlocked(alerts)
                        return token
            return None

    def consume_confirmation_token(self, proposal_id: str, token: str) -> bool:
        """Consume a matching confirmation token for a proposal."""

        now = datetime.now(UTC)
        with self._lock:
            alerts = self._read_alerts_unlocked()
            for alert in alerts:
                for proposal in alert.get("proposals", []):
                    if proposal["id"] != proposal_id:
                        continue
                    stored = proposal.get("confirmation_token")
                    expires_raw = proposal.get("confirmation_token_expires_at")
                    expires_at = None
                    if expires_raw:
                        try:
                            expires_at = datetime.fromisoformat(expires_raw)
                        except ValueError:
                            expires_at = None
                    is_valid = stored == token and expires_at is not None and expires_at > now
                    proposal.pop("confirmation_token", None)
                    proposal.pop("confirmation_token_expires_at", None)
                    self._write_alerts_unlocked(alerts)
                    return is_valid
            return False

    # ── Briefing cache ──────────────────────────────────────────────────

    def get_briefing_cache(self, max_age_hours: float = 6.0) -> dict | None:
        """Return cached briefing if still fresh, else None."""
        path = _DATA_DIR / "briefing.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            generated = datetime.fromisoformat(data.get("generated_at", ""))
            if datetime.now() - generated.replace(tzinfo=None) < timedelta(hours=max_age_hours):
                return data
        except Exception:
            pass
        return None

    def save_briefing_cache(self, briefing: dict) -> None:
        _DATA_DIR.mkdir(exist_ok=True)
        (_DATA_DIR / "briefing.json").write_text(json.dumps(briefing, indent=2))

    # ── Exit target tracking ────────────────────────────────────────────

    def mark_exit_alerted(self, proposal_id: str) -> None:
        """Mark a proposal so we don't fire the same exit alert twice."""
        with self._lock:
            alerts = self._read_alerts_unlocked()
            for alert in alerts:
                for proposal in alert.get("proposals", []):
                    if proposal["id"] == proposal_id:
                        proposal["exit_alerted"] = True
                        self._write_alerts_unlocked(alerts)
                        return

    def set_exit_targets(self, proposal_id: str, target_price: float, stop_price: float) -> None:
        """Attach target/stop prices to an executed proposal."""
        with self._lock:
            alerts = self._read_alerts_unlocked()
            for alert in alerts:
                for proposal in alert.get("proposals", []):
                    if proposal["id"] == proposal_id:
                        proposal["target_price"] = target_price
                        proposal["stop_price"] = stop_price
                        proposal["executed_at"] = datetime.now().isoformat()
                        self._write_alerts_unlocked(alerts)
                        return

    # ── Symbol muting ───────────────────────────────────────────────────

    def _mute_path(self) -> Path:
        _DATA_DIR.mkdir(exist_ok=True)
        return _DATA_DIR / "muted.json"

    def get_muted_symbols(self) -> dict[str, str]:
        """Return {symbol: muted_until_ISO} dict, purging expired entries."""
        path = self._mute_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
            now = datetime.now()
            active = {
                sym: until
                for sym, until in data.items()
                if datetime.fromisoformat(until) > now
            }
            if len(active) != len(data):
                path.write_text(json.dumps(active, indent=2))
            return active
        except Exception:
            return {}

    def mute_symbol(self, symbol: str, days: int = 7) -> None:
        data = self.get_muted_symbols()
        data[symbol.upper()] = (datetime.now() + timedelta(days=days)).isoformat()
        self._mute_path().write_text(json.dumps(data, indent=2))

    def unmute_symbol(self, symbol: str) -> None:
        data = self.get_muted_symbols()
        data.pop(symbol.upper(), None)
        self._mute_path().write_text(json.dumps(data, indent=2))

    def get_recent_flag_keys(self, hours: int = 24) -> set[tuple[str, str]]:
        """Return (type, symbol) pairs from any alert in the last ``hours`` hours.

        Checks ALL statuses (pending, approved, denied) so that acknowledging or
        dismissing a scan doesn't cause the same flags to be re-raised on the very
        next scheduled check.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        keys: set[tuple[str, str]] = set()
        for alert in self.load_all():
            ts_raw = alert.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except Exception:
                continue
            if ts < cutoff:
                break  # alerts are stored newest-first; stop once we're past the window
            for f in alert.get("flags", []):
                keys.add((f["type"], f["symbol"]))
        return keys

    def _find_proposal_by_token_unlocked(self, token: str) -> tuple[dict | None, dict | None]:
        alerts = self._read_alerts_unlocked()
        for alert in alerts:
            for proposal in alert.get("proposals", []):
                if proposal.get("approval_token") == token or proposal.get("denial_token") == token:
                    return proposal, alert
        return None, None

    def _read_alerts_unlocked(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text())
        except Exception:
            return []

    def _write_alerts_unlocked(self, alerts: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: str | None = None
        try:
            fd, temp_path = tempfile.mkstemp(
                dir=str(self._path.parent),
                prefix=f"{self._path.name}.",
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(alerts, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._path)
        finally:
            if temp_path is not None and os.path.exists(temp_path):
                os.unlink(temp_path)
