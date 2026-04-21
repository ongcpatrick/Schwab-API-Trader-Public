"""Twilio SMS notifications for portfolio alerts."""

from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Return the machine's LAN IP address for SMS dashboard links."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def send_alert_sms(
    alert: dict,
    *,
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    dashboard_url: str = "",
) -> bool:
    """Send an SMS alert via Twilio. Returns True on success."""
    try:
        from twilio.rest import Client  # type: ignore[import]
    except ImportError:
        logger.error("twilio package not installed — run: uv add twilio")
        return False

    try:
        flags = alert.get("flags", [])
        severity_icon = {"HIGH": "🚨", "MEDIUM": "⚠️", "LOW": "ℹ️"}

        lines: list[str] = [
            f"{'🚨' if any(f['severity'] == 'HIGH' for f in flags) else '⚠️'} "
            f"Portfolio Alert — {len(flags)} flag(s)",
            "",
        ]
        for f in flags[:4]:
            icon = severity_icon.get(f["severity"], "•")
            lines.append(f"{icon} {f['description']}")
        if len(flags) > 4:
            lines.append(f"...and {len(flags) - 4} more")

        url = dashboard_url or f"http://{get_local_ip()}:8000/dashboard"
        lines += ["", f"Dashboard: {url}"]

        client = Client(account_sid, auth_token)
        client.messages.create(body="\n".join(lines), from_=from_number, to=to_number)
        logger.info("Alert SMS sent to %s", to_number)
        return True

    except Exception:
        logger.exception("SMS send failed")
        return False
