"""HTML email notifications for trade approval — stdlib smtplib, no extra deps."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_MAX_REASONING_CHARS = 320


def send_sell_email(
    proposals: list[dict],
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_address: str,
    to_address: str,
    base_url: str,
) -> bool:
    """Send a minimal HTML email with full-width approve/deny buttons for sell proposals."""
    if not proposals:
        return False

    symbols = [p["symbol"] for p in proposals]
    total_proceeds = sum(
        float(p.get("limit_price") or 0) * int(p.get("quantity") or 0)
        for p in proposals
    )
    n = len(proposals)
    sym_str = " · ".join(symbols)
    proceeds_str = f"${total_proceeds:,.0f}" if total_proceeds else ""
    subject = f"SELL {sym_str} — {n} proposal{'s' if n > 1 else ''}{f' · {proceeds_str}' if proceeds_str else ''}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address
    msg.attach(MIMEText(_build_sell_plain(proposals, base_url), "plain"))
    msg.attach(MIMEText(_build_sell_html(proposals, base_url, total_proceeds), "html"))

    def _ssl_ctx() -> ssl.SSLContext:
        try:
            import certifi  # type: ignore[import]
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    try:
        ctx = _ssl_ctx()
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(from_address, to_address, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.login(smtp_user, smtp_password)
                server.sendmail(from_address, to_address, msg.as_string())
        logger.info("Sell email sent to %s (%d proposal(s))", to_address, len(proposals))
        return True
    except Exception as exc:
        logger.error("Failed to send sell email: %s", exc)
        return False


def _build_sell_plain(proposals: list[dict], base_url: str) -> str:
    lines = ["SELL PROPOSALS — schwab-ai-trader", "=" * 40, ""]
    for p in proposals:
        price = float(p.get("limit_price") or 0)
        qty = int(p.get("quantity") or 0)
        total = price * qty
        price_str = f"@ ${price:,.2f}" if price else "@ market"
        proceeds_str = f" = ${total:,.0f}" if total else ""
        lines.append(f"SELL {p['symbol']}: {qty} sh {price_str}{proceeds_str}")
        lines.append(f"  {_truncate_reasoning(p.get('reasoning', ''))}")
        lines.append("")
        lines.append(f"  APPROVE: {base_url}/trade/approve/{p['approval_token']}")
        lines.append(f"  DENY:    {base_url}/trade/deny/{p['denial_token']}")
        lines.append("")
    lines.append("Links expire in 24 hours.")
    return "\n".join(lines)


def _build_sell_html(proposals: list[dict], base_url: str, total_proceeds: float) -> str:
    urgency_color = {
        "HIGH":   ("#ff6b6b", "rgba(255,107,107,0.12)"),
        "MEDIUM": ("#fbbf24", "rgba(251,191,36,0.10)"),
        "LOW":    ("#34d399", "rgba(52,211,153,0.10)"),
    }

    cards_html = ""
    for p in proposals:
        approve_url = f"{base_url}/trade/approve/{p['approval_token']}"
        deny_url = f"{base_url}/trade/deny/{p['denial_token']}"

        qty = int(p.get("quantity") or 0)
        price = float(p.get("limit_price") or 0)
        total = qty * price
        urg = p.get("urgency", "MEDIUM")
        urg_fg, urg_bg = urgency_color.get(urg, urgency_color["MEDIUM"])

        price_disp = f"${price:,.2f}" if price else "market"
        total_disp = f"${total:,.0f}" if total else "—"
        eq_line = f"{qty} sh × {price_disp} = {total_disp} proceeds" if price else f"{qty} sh @ market"

        reasoning = _truncate_reasoning(p.get("reasoning", ""))

        cards_html += f"""
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
    <tr><td style="background:#0e1318;border:1px solid rgba(255,255,255,0.08);border-radius:10px;overflow:hidden;">

      <!-- Symbol header -->
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding:16px 20px 12px;">
            <table cellpadding="0" cellspacing="0"><tr>
              <td style="padding-right:9px;">
                <span style="font-size:20px;font-weight:800;letter-spacing:-0.03em;color:#ffffff;">{p['symbol']}</span>
              </td>
              <td style="vertical-align:middle;padding-right:7px;">
                <span style="display:inline-block;background:#3b0a0a;color:#f87171;border:1px solid rgba(248,113,113,0.3);border-radius:4px;padding:2px 7px;font-size:10px;font-weight:800;letter-spacing:.07em;">SELL</span>
              </td>
              <td style="vertical-align:middle;">
                <span style="display:inline-block;background:{urg_bg};color:{urg_fg};border-radius:4px;padding:2px 7px;font-size:10px;font-weight:700;letter-spacing:.06em;">{urg}</span>
              </td>
            </tr></table>
            <div style="font-size:13px;font-weight:600;color:#8b949e;margin-top:7px;font-variant-numeric:tabular-nums;">{eq_line}</div>
          </td>
        </tr>
      </table>

      <!-- Reasoning -->
      <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid rgba(255,255,255,0.06);">
        <tr>
          <td style="padding:12px 20px;">
            <div style="font-size:12px;color:#8b949e;line-height:1.6;">{reasoning}</div>
          </td>
        </tr>
      </table>

      <!-- Full-width stacked buttons -->
      <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid rgba(255,255,255,0.06);">
        <tr>
          <td style="padding:12px 20px 16px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:6px;">
              <tr>
                <td align="center" bgcolor="#7f1d1d" style="border-radius:7px;">
                  <a href="{approve_url}" style="display:block;padding:12px;font-size:14px;font-weight:700;color:#ffffff;text-decoration:none;text-align:center;letter-spacing:.01em;">Approve Sell</a>
                </td>
              </tr>
            </table>
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center">
                  <a href="{deny_url}" style="display:block;padding:7px;font-size:12px;color:#6e7681;text-decoration:none;text-align:center;">Deny</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>

    </td></tr>
  </table>"""

    n = len(proposals)
    proceeds_line = f"${total_proceeds:,.0f} proceeds" if total_proceeds else ""
    budget_line = f"{n} proposal{'s' if n > 1 else ''}{f' · {proceeds_line}' if proceeds_line else ''}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Sell Proposals</title>
</head>
<body style="margin:0;padding:0;background:#080b10;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:28px 16px 48px;">
        <table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="padding-bottom:18px;">
              <div style="font-size:10px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:#ef4444;margin-bottom:8px;">Schwab AI Trader</div>
              <div style="font-size:13px;font-weight:600;color:#8b949e;">{budget_line}</div>
              <div style="font-size:11px;color:#484f58;margin-top:3px;">Links expire in 24 hours</div>
            </td>
          </tr>

          <!-- Cards -->
          <tr><td>{cards_html}</td></tr>

          <!-- Footer -->
          <tr>
            <td style="padding-top:4px;border-top:1px solid rgba(255,255,255,0.05);">
              <p style="font-size:11px;color:#484f58;line-height:1.6;margin:10px 0 0;">
                These links place <strong style="color:#6e7681;">real orders</strong> on your Schwab account.&nbsp;·&nbsp;<a href="{base_url}/dashboard" style="color:#2563eb;text-decoration:none;">Open dashboard</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_approval_email(
    proposals: list[dict],
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_address: str,
    to_address: str,
    base_url: str,
) -> bool:
    """Send a minimal HTML email with full-width approve/deny buttons per proposal.

    Returns True on success, False on any SMTP error.
    """
    if not proposals:
        return False

    symbols = [p["symbol"] for p in proposals]
    total_cost = sum(
        float(p.get("limit_price") or 0) * int(p.get("quantity") or 0)
        for p in proposals
    )
    n = len(proposals)
    sym_str = " · ".join(symbols)
    cost_str = f"${total_cost:,.0f}" if total_cost else ""
    subject = f"BUY {sym_str} — {n} proposal{'s' if n > 1 else ''}{f' · {cost_str}' if cost_str else ''}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address
    msg.attach(MIMEText(_build_plain(proposals, base_url), "plain"))
    msg.attach(MIMEText(_build_html(proposals, base_url, total_cost), "html"))

    def _ssl_ctx() -> ssl.SSLContext:
        try:
            import certifi  # type: ignore[import]
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    try:
        ctx = _ssl_ctx()
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(from_address, to_address, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.login(smtp_user, smtp_password)
                server.sendmail(from_address, to_address, msg.as_string())
        logger.info("Approval email sent to %s (%d proposal(s))", to_address, len(proposals))
        return True
    except Exception as exc:
        logger.error("Failed to send approval email: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _truncate_reasoning(text: str) -> str:
    if len(text) <= _MAX_REASONING_CHARS:
        return text
    return text[:_MAX_REASONING_CHARS].rsplit(" ", 1)[0] + "…"


def _build_plain(proposals: list[dict], base_url: str) -> str:
    lines = ["TRADE PROPOSALS — schwab-ai-trader", "=" * 40, ""]
    for p in proposals:
        price = float(p.get("limit_price") or 0)
        qty = int(p.get("quantity") or 0)
        total = price * qty
        price_str = f"@ ${price:,.2f}" if price else "@ market"
        cost_str = f" = ${total:,.0f}" if total else ""
        upside = p.get("analyst_upside_pct")
        upside_str = f" | analyst +{float(upside):.0f}%" if upside is not None else ""
        lines.append(f"BUY {p['symbol']}: {qty} sh {price_str}{cost_str}{upside_str}")
        lines.append(f"  {_truncate_reasoning(p.get('reasoning', ''))}")
        lines.append("")
        lines.append(f"  APPROVE: {base_url}/trade/approve/{p['approval_token']}")
        lines.append(f"  DENY:    {base_url}/trade/deny/{p['denial_token']}")
        lines.append("")
    lines.append("Links expire in 24 hours.")
    return "\n".join(lines)


def _build_html(proposals: list[dict], base_url: str, total_cost: float) -> str:
    urgency_color = {
        "HIGH":   ("#ff6b6b", "rgba(255,107,107,0.12)"),
        "MEDIUM": ("#fbbf24", "rgba(251,191,36,0.10)"),
        "LOW":    ("#34d399", "rgba(52,211,153,0.10)"),
    }

    cards_html = ""
    for p in proposals:
        approve_url = f"{base_url}/trade/approve/{p['approval_token']}"
        deny_url = f"{base_url}/trade/deny/{p['denial_token']}"

        qty = int(p.get("quantity") or 0)
        price = float(p.get("limit_price") or 0)
        total = qty * price
        urg = p.get("urgency", "MEDIUM")
        urg_fg, urg_bg = urgency_color.get(urg, urgency_color["MEDIUM"])

        price_disp = f"${price:,.2f}" if price else "market"
        total_disp = f"${total:,.0f}" if total else "—"
        eq_line = f"{qty} sh × {price_disp} = {total_disp}" if price else f"{qty} sh @ market"

        # Key metrics (only show fields that were populated by the agent)
        upside = p.get("analyst_upside_pct")
        target = p.get("analyst_target")
        fwd_pe = p.get("forward_pe")
        sector = p.get("sector") or ""

        metric_cells = ""
        if upside is not None:
            fg = "#22c55e" if float(upside) >= 15 else "#e6edf3"
            metric_cells += (
                f'<td style="padding-right:24px;">'
                f'<div style="font-size:10px;color:#6e7681;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;">Analyst Upside</div>'
                f'<div style="font-size:16px;font-weight:700;color:{fg};">+{float(upside):.0f}%</div>'
                f"</td>"
            )
        if target is not None:
            metric_cells += (
                f'<td style="padding-right:24px;">'
                f'<div style="font-size:10px;color:#6e7681;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;">Target</div>'
                f'<div style="font-size:16px;font-weight:700;color:#e6edf3;">${float(target):,.2f}</div>'
                f"</td>"
            )
        if fwd_pe is not None:
            metric_cells += (
                f'<td style="padding-right:24px;">'
                f'<div style="font-size:10px;color:#6e7681;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;">Fwd P/E</div>'
                f'<div style="font-size:16px;font-weight:700;color:#e6edf3;">{float(fwd_pe):.1f}x</div>'
                f"</td>"
            )
        if sector:
            metric_cells += (
                f"<td>"
                f'<div style="font-size:10px;color:#6e7681;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;">Sector</div>'
                f'<div style="font-size:13px;font-weight:600;color:#8b949e;">{sector}</div>'
                f"</td>"
            )

        metrics_block = ""
        if metric_cells:
            metrics_block = (
                '<table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid rgba(255,255,255,0.06);">'
                "<tr><td style=\"padding:12px 20px;\">"
                '<table cellpadding="0" cellspacing="0"><tr>'
                + metric_cells
                + "</tr></table></td></tr></table>"
            )

        reasoning = _truncate_reasoning(p.get("reasoning", ""))

        cards_html += f"""
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
    <tr><td style="background:#0e1318;border:1px solid rgba(255,255,255,0.08);border-radius:10px;overflow:hidden;">

      <!-- Symbol header -->
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding:16px 20px 12px;">
            <table cellpadding="0" cellspacing="0"><tr>
              <td style="padding-right:9px;">
                <span style="font-size:20px;font-weight:800;letter-spacing:-0.03em;color:#ffffff;">{p['symbol']}</span>
              </td>
              <td style="vertical-align:middle;padding-right:7px;">
                <span style="display:inline-block;background:#163523;color:#3fb950;border:1px solid rgba(63,185,80,0.3);border-radius:4px;padding:2px 7px;font-size:10px;font-weight:800;letter-spacing:.07em;">BUY</span>
              </td>
              <td style="vertical-align:middle;">
                <span style="display:inline-block;background:{urg_bg};color:{urg_fg};border-radius:4px;padding:2px 7px;font-size:10px;font-weight:700;letter-spacing:.06em;">{urg}</span>
              </td>
            </tr></table>
            <div style="font-size:13px;font-weight:600;color:#8b949e;margin-top:7px;font-variant-numeric:tabular-nums;">{eq_line}</div>
          </td>
        </tr>
      </table>

      {metrics_block}

      <!-- Reasoning -->
      <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid rgba(255,255,255,0.06);">
        <tr>
          <td style="padding:12px 20px;">
            <div style="font-size:12px;color:#8b949e;line-height:1.6;">{reasoning}</div>
          </td>
        </tr>
      </table>

      <!-- Full-width stacked buttons -->
      <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid rgba(255,255,255,0.06);">
        <tr>
          <td style="padding:12px 20px 16px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:6px;">
              <tr>
                <td align="center" bgcolor="#166534" style="border-radius:7px;">
                  <a href="{approve_url}" style="display:block;padding:12px;font-size:14px;font-weight:700;color:#ffffff;text-decoration:none;text-align:center;letter-spacing:.01em;">Approve Trade</a>
                </td>
              </tr>
            </table>
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center">
                  <a href="{deny_url}" style="display:block;padding:7px;font-size:12px;color:#6e7681;text-decoration:none;text-align:center;">Deny</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>

    </td></tr>
  </table>"""

    n = len(proposals)
    cost_line = f"${total_cost:,.0f} total" if total_cost else ""
    budget_line = f"{n} proposal{'s' if n > 1 else ''}{f' · {cost_line}' if cost_line else ''}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Buy Proposals</title>
</head>
<body style="margin:0;padding:0;background:#080b10;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:28px 16px 48px;">
        <table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="padding-bottom:18px;">
              <div style="font-size:10px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:#2563eb;margin-bottom:8px;">Schwab AI Trader</div>
              <div style="font-size:13px;font-weight:600;color:#8b949e;">{budget_line}</div>
              <div style="font-size:11px;color:#484f58;margin-top:3px;">Links expire in 24 hours</div>
            </td>
          </tr>

          <!-- Cards -->
          <tr><td>{cards_html}</td></tr>

          <!-- Footer -->
          <tr>
            <td style="padding-top:4px;border-top:1px solid rgba(255,255,255,0.05);">
              <p style="font-size:11px;color:#484f58;line-height:1.6;margin:10px 0 0;">
                These links place <strong style="color:#6e7681;">real orders</strong> on your Schwab account.&nbsp;·&nbsp;<a href="{base_url}/dashboard" style="color:#2563eb;text-decoration:none;">Open dashboard</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
