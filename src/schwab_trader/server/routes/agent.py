"""Trading agent routes — manual trigger, alert list, approve/deny, buy-scan."""

from __future__ import annotations

import logging
import socket
import time as _time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
import re as _re

from pydantic import BaseModel, field_validator

from schwab_trader.advisor.service import AdvisorService
from schwab_trader.agent.service import AgentService
from schwab_trader.agent.store import AlertStore
from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.core.settings import get_settings
from schwab_trader.execution.audit import ExecutionAuditStore
from schwab_trader.execution.service import ExecutionService, ProposalExecutionError
from schwab_trader.server.dependencies import get_broker_service

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Rate limiting — import shared limiter from app factory
# ---------------------------------------------------------------------------
def _get_limiter():
    from schwab_trader.server.app import limiter
    return limiter

# Cooldown lock: maps proposal_id/sell-key → last execution timestamp
# Prevents double-click / duplicate submissions within 10 seconds
_execution_cooldown: dict[str, float] = {}
_COOLDOWN_SECONDS = 10


def _check_cooldown(key: str) -> None:
    """Raise 429 if this key was executed within the cooldown window."""
    last = _execution_cooldown.get(key, 0)
    if _time.monotonic() - last < _COOLDOWN_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Order already submitted. Wait {_COOLDOWN_SECONDS}s before retrying.",
        )


def _record_cooldown(key: str) -> None:
    _execution_cooldown[key] = _time.monotonic()
    # Prune stale entries to prevent unbounded growth
    cutoff = _time.monotonic() - 300
    stale = [k for k, v in _execution_cooldown.items() if v < cutoff]
    for k in stale:
        del _execution_cooldown[k]

# Module-level singletons shared with the scheduler
_store = AlertStore()
_agent = AgentService(store=_store)
_audit_store = ExecutionAuditStore()


def get_agent_service() -> AgentService:
    return _agent


def get_alert_store() -> AlertStore:
    return _store


def _get_execution_service(broker_service: SchwabBrokerService) -> ExecutionService:
    return ExecutionService(
        broker_service=broker_service,
        settings=get_settings(),
        audit_store=_audit_store,
    )


def _make_advisor(broker_service: SchwabBrokerService) -> AdvisorService:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY not configured.",
        )
    return AdvisorService(broker_service=broker_service, api_key=settings.anthropic_api_key)


def run_scheduled_check() -> dict | None:
    """Called by the background scheduler — builds its own services."""
    from schwab_trader.server.dependencies import get_broker_service as _gbk

    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning("Skipping agent check — ANTHROPIC_API_KEY not set")
        return None

    try:
        broker_service = _gbk()
        advisor = AdvisorService(broker_service=broker_service, api_key=settings.anthropic_api_key)
        alert = _agent.run_check(broker_service, advisor, settings=settings)

        return alert
    except Exception:
        logger.exception("Scheduled agent check failed")
        return None


@router.post("/run-check")
def run_check(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Manually trigger a portfolio scan. Returns the new alert or a no-flags message."""
    settings = get_settings()
    advisor = _make_advisor(broker_service)
    alert = _agent.run_check(broker_service, advisor, settings=settings)

    if alert:
        return {"status": "alert_created", "alert": alert}
    return {"status": "no_flags", "message": "Portfolio looks clean — no actionable flags."}


@router.get("/alerts")
def list_alerts(limit: int = 20) -> list[dict]:
    """Return recent alerts (latest first)."""
    return _store.load_all()[:limit]


@router.post("/alerts/{alert_id}/approve")
def approve_alert(alert_id: str) -> dict:
    """Mark an alert as approved."""
    if not _store.update_status(alert_id, "approved"):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "approved"}


@router.post("/alerts/{alert_id}/deny")
def deny_alert(alert_id: str) -> dict:
    """Mark an alert as denied/dismissed."""
    if not _store.update_status(alert_id, "denied"):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "denied"}


@router.post("/proposals/{proposal_id}/execute")
def execute_proposal(
    proposal_id: str,
    request: Request,
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Preview then execute a trade proposal after user confirmation."""
    _check_cooldown(f"proposal:{proposal_id}")

    proposal, _ = _store.find_proposal_by_id(proposal_id)

    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.get("status") == "executed":
        raise HTTPException(status_code=409, detail="Proposal already executed")

    try:
        result = _get_execution_service(broker_service).execute_proposal(
            proposal,
            source="dashboard",
        )
    except ProposalExecutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    _record_cooldown(f"proposal:{proposal_id}")
    _store.update_proposal_status(proposal_id, "executed")

    # Attach target (+30%) and stop (-15%) prices for exit monitoring
    limit_price = proposal.get("limit_price")
    if proposal.get("action") == "BUY" and limit_price:
        entry = float(limit_price)
        _store.set_exit_targets(
            proposal_id,
            target_price=round(entry * 1.30, 2),
            stop_price=round(entry * 0.85, 2),
        )

    return result


@router.post("/proposals/{proposal_id}/cancel")
def cancel_proposal(proposal_id: str) -> dict:
    """Cancel a pending trade proposal without executing."""
    if not _store.update_proposal_status(proposal_id, "cancelled"):
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"status": "cancelled"}


class SellOrderRequest(BaseModel):
    symbol: str
    action: str = "SELL"
    quantity: int
    order_type: str = "LIMIT"
    limit_price: float | None = None
    reasoning: str = "Manual sell from dashboard"

    @field_validator("symbol", mode="before")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = str(v).strip().upper()
        if not _re.fullmatch(r"[A-Z]{1,5}", v):
            raise ValueError(f"Invalid symbol '{v}' — must be 1–5 uppercase letters (A-Z)")
        return v

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v) -> int:
        v = int(v)
        if v <= 0:
            raise ValueError("Quantity must be a positive integer")
        if v > 10_000:
            raise ValueError("Quantity exceeds maximum single-order limit (10,000 shares)")
        return v

    @field_validator("order_type", mode="before")
    @classmethod
    def validate_order_type(cls, v: str) -> str:
        v = str(v).upper()
        if v not in ("MARKET", "LIMIT"):
            raise ValueError("order_type must be MARKET or LIMIT")
        return v


class SellAnalysisRequest(BaseModel):
    symbol: str
    qty_held: float
    avg_cost: float
    current_price: float
    total_pnl_pct: float
    day_pnl_pct: float
    portfolio_weight_pct: float


_SELL_ANALYSIS_SYSTEM = """\
You are a sharp, tax-aware portfolio advisor. The user is considering selling a position.
Your job is to analyze whether they should sell, trim, or hold — and exactly how many shares if selling.

You have access to tools:
- get_news: recent headlines, analyst ratings, and sentiment for the symbol
- get_earnings_calendar: upcoming earnings dates (never sell right before earnings without good reason)
- get_stock_fundamentals: analyst price targets, forward PE, revenue growth

Use 2-3 tool calls max. Be direct. No disclaimers.

Respond ONLY with a JSON object. No markdown, no prose outside the JSON:
{
  "action": "SELL_ALL" | "SELL_PARTIAL" | "HOLD" | "TRIM",
  "suggested_quantity": <integer or null>,
  "suggested_price": <float or null — limit price recommendation or null for market>,
  "conviction": "HIGH" | "MEDIUM" | "LOW",
  "headline": "<one short sentence — the single most important reason>",
  "reasoning": "<2-4 sentence explanation covering: momentum/trend, upcoming catalysts, tax angle if relevant, position sizing>",
  "risk_factors": "<1-2 sentence on what could go wrong with this recommendation>"
}
"""


@router.post("/analyze-sell")
def analyze_sell(
    req: SellAnalysisRequest,
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Run a focused AI analysis on whether/how much to sell a position."""
    import json as _json

    advisor = _make_advisor(broker_service)

    prompt = (
        f"I hold {req.qty_held:.0f} shares of {req.symbol} with an average cost of ${req.avg_cost:.2f}. "
        f"Current price is ${req.current_price:.2f}. "
        f"Total P&L: {req.total_pnl_pct:+.1f}%. Today: {req.day_pnl_pct:+.1f}%. "
        f"This position is {req.portfolio_weight_pct:.1f}% of my portfolio.\n\n"
        f"Analyze {req.symbol} right now. Should I sell all, trim, or hold? "
        f"If selling or trimming, exactly how many shares and at what limit price? "
        f"Use your tools to check recent news, upcoming earnings, and analyst targets before answering."
    )

    raw = advisor.run_agent(prompt, system_override=_SELL_ANALYSIS_SYSTEM, max_rounds=4)

    # Strip any markdown code fences if the model wrapped the JSON
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        result = _json.loads(cleaned)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=502, detail=f"AI returned unparseable response: {raw[:200]}")

    return result


@router.post("/notify")
def send_notification(body: Annotated[dict, Body()]) -> dict:
    """Send an SMS alert from a cloud routine.

    Body: {"message": "...", "urgent": false}
    The server has Twilio credentials — routines don't need them directly.
    """
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required")

    settings = get_settings()
    if not all([
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_from_number,
        settings.alert_phone_number,
    ]):
        return {"status": "skipped", "reason": "Twilio not configured"}

    urgent = bool(body.get("urgent", False))
    if urgent:
        message = f"URGENT: {message}"

    from schwab_trader.notifications.sms import send_alert_sms
    sent = send_alert_sms(
        {"flags": [{"severity": "HIGH" if urgent else "MEDIUM", "description": message}]},
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_from_number,
        to_number=settings.alert_phone_number,
        dashboard_url=settings.dashboard_url,
    )
    return {"status": "sent" if sent else "failed"}


@router.post("/place-sell-order")
def place_sell_order(
    req: SellOrderRequest,
    request: Request,
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Place a manual sell order directly from the portfolio view."""
    cooldown_key = f"sell:{req.symbol.upper()}:{req.quantity}"
    _check_cooldown(cooldown_key)

    proposal = {
        "id": f"manual-sell-{req.symbol}-{int(datetime.now(UTC).timestamp())}",
        "symbol": req.symbol.upper(),
        "action": "SELL",
        "quantity": req.quantity,
        "order_type": req.order_type.upper(),
        "limit_price": req.limit_price,
        "reasoning": req.reasoning,
    }

    try:
        result = _get_execution_service(broker_service).execute_proposal(proposal, source="dashboard_sell")
    except ProposalExecutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    _record_cooldown(cooldown_key)
    return result


# ---------------------------------------------------------------------------
# Direct order — used by autonomous cloud routines (no approval loop)
# ---------------------------------------------------------------------------

class DirectOrderRequest(BaseModel):
    """Schema for autonomous bot order placement."""

    symbol: str
    action: str  # BUY or SELL
    quantity: float
    order_type: str = "LIMIT"
    limit_price: float | None = None
    reasoning: str = ""

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("action")
    @classmethod
    def _upper_action(cls, v: str) -> str:
        v = v.upper().strip()
        if v not in ("BUY", "SELL"):
            raise ValueError("action must be BUY or SELL")
        return v

    @field_validator("order_type")
    @classmethod
    def _upper_order_type(cls, v: str) -> str:
        v = v.upper().strip()
        if v not in ("LIMIT", "MARKET"):
            raise ValueError("order_type must be LIMIT or MARKET")
        return v

    @field_validator("quantity")
    @classmethod
    def _positive_quantity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v


@router.post("/direct-order")
def direct_order(
    req: DirectOrderRequest,
    request: Request,
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Place an order directly — for use by autonomous cloud routines.

    Bypasses the proposal store / approval flow but still runs the full
    ExecutionService path (kill switch + risk checks + preview + place).
    Callers must supply a documented reasoning string.
    """
    if not req.reasoning.strip():
        raise HTTPException(
            status_code=422,
            detail="reasoning is required for direct-order calls (document the trade thesis).",
        )

    cooldown_key = f"direct:{req.action}:{req.symbol}:{req.quantity}"
    _check_cooldown(cooldown_key)

    proposal = {
        "id": f"direct-{req.action.lower()}-{req.symbol}-{int(datetime.now(UTC).timestamp())}",
        "symbol": req.symbol,
        "action": req.action,
        "quantity": req.quantity,
        "order_type": req.order_type,
        "limit_price": req.limit_price,
        "reasoning": req.reasoning,
    }

    try:
        result = _get_execution_service(broker_service).execute_proposal(
            proposal, source="direct_order"
        )
    except ProposalExecutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    _record_cooldown(cooldown_key)
    return result


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_base_url(settings) -> str:
    url = settings.dashboard_url
    if url:
        return url.rstrip("/")
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "127.0.0.1"
    return f"http://{ip}:8000"


def _send_buy_notifications(alert: dict, settings) -> None:
    """Send SMS and/or email for a buy-scan alert."""
    proposals = [p for p in alert.get("proposals", []) if p.get("status") == "pending"]
    if not proposals:
        return
    base_url = _get_base_url(settings)

    # SMS
    if all([settings.twilio_account_sid, settings.twilio_auth_token,
            settings.twilio_from_number, settings.alert_phone_number]):
        try:
            from twilio.rest import Client  # type: ignore[import]
            lines = [f"📈 Buy Scan — {len(proposals)} proposal{'s' if len(proposals) > 1 else ''}"]
            for p in proposals:
                price = f"${p['limit_price']}" if p.get("limit_price") else "mkt"
                est = ""
                if p.get("limit_price") and p.get("quantity"):
                    est = f" ~${float(p['limit_price']) * float(p['quantity']):,.0f}"
                lines.append(f"\nBUY {p['quantity']} {p['symbol']} {price}{est}")
                lines.append(f"✅ {base_url}/trade/approve/{p['approval_token']}")
                lines.append(f"❌ {base_url}/trade/deny/{p['denial_token']}")
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            client.messages.create(
                body="\n".join(lines),
                from_=settings.twilio_from_number,
                to=settings.alert_phone_number,
            )
            _store.mark_sms_sent(alert["id"])
            logger.info("Buy scan SMS sent for alert %s", alert["id"])
        except Exception as exc:
            logger.warning("Buy scan SMS failed: %s", exc)

    # Email — only send if at least one proposal clears the minimum upside threshold
    if all([settings.email_smtp_host, settings.email_smtp_user,
            settings.email_smtp_password, settings.alert_email_address]):
        min_upside = settings.email_min_upside_pct
        qualifying = [
            p for p in proposals
            if min_upside <= 0 or float(p.get("analyst_upside_pct") or 0) >= min_upside
        ]
        if not qualifying:
            logger.info(
                "Skipping buy scan email — no proposals meet the %.0f%% upside threshold",
                min_upside,
            )
        else:
            try:
                from schwab_trader.notifications.email import send_approval_email
                sent = send_approval_email(
                    qualifying,
                    smtp_host=settings.email_smtp_host,
                    smtp_port=settings.email_smtp_port,
                    smtp_user=settings.email_smtp_user,
                    smtp_password=settings.email_smtp_password,
                    from_address=settings.email_smtp_user,
                    to_address=settings.alert_email_address,
                    base_url=base_url,
                )
                if sent:
                    _store.mark_email_sent(alert["id"])
            except Exception as exc:
                logger.warning("Buy scan email failed: %s", exc)


def _send_sell_notifications(alert: dict, settings) -> None:
    """Send SMS and/or email for a sell-scan alert."""
    proposals = [p for p in alert.get("proposals", []) if p.get("status") == "pending"]
    if not proposals:
        return
    base_url = _get_base_url(settings)

    # SMS
    if all([settings.twilio_account_sid, settings.twilio_auth_token,
            settings.twilio_from_number, settings.alert_phone_number]):
        try:
            from twilio.rest import Client  # type: ignore[import]
            lines = [f"📉 Sell Scan — {len(proposals)} proposal{'s' if len(proposals) > 1 else ''}"]
            for p in proposals:
                price = f"${p['limit_price']}" if p.get("limit_price") else "mkt"
                est = ""
                if p.get("limit_price") and p.get("quantity"):
                    est = f" ~${float(p['limit_price']) * float(p['quantity']):,.0f}"
                lines.append(f"\nSELL {p['quantity']:.0f} {p['symbol']} {price}{est}")
                lines.append(f"✅ {base_url}/trade/approve/{p['approval_token']}")
                lines.append(f"❌ {base_url}/trade/deny/{p['denial_token']}")
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            client.messages.create(
                body="\n".join(lines),
                from_=settings.twilio_from_number,
                to=settings.alert_phone_number,
            )
            _store.mark_sms_sent(alert["id"])
            logger.info("Sell scan SMS sent for alert %s", alert["id"])
        except Exception as exc:
            logger.warning("Sell scan SMS failed: %s", exc)

    # Email
    if all([settings.email_smtp_host, settings.email_smtp_user,
            settings.email_smtp_password, settings.alert_email_address]):
        try:
            from schwab_trader.notifications.email import send_sell_email
            sent = send_sell_email(
                proposals,
                smtp_host=settings.email_smtp_host,
                smtp_port=settings.email_smtp_port,
                smtp_user=settings.email_smtp_user,
                smtp_password=settings.email_smtp_password,
                from_address=settings.email_smtp_user,
                to_address=settings.alert_email_address,
                base_url=base_url,
            )
            if sent:
                _store.mark_email_sent(alert["id"])
        except Exception as exc:
            logger.warning("Sell scan email failed: %s", exc)


def _result_html(title: str, body: str, success: bool = True) -> str:
    color = "#3fb950" if success else "#f85149"
    icon = "✅" if success else "❌"
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{title}</title>
</head>
<body
  style="margin:0;padding:0;background:#0d1117;color:#e6edf3;
         font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         display:flex;align-items:center;justify-content:center;min-height:100vh;"
>
  <div style="text-align:center;padding:40px 24px;max-width:400px;">
    <div style="font-size:48px;margin-bottom:16px;">{icon}</div>
    <h1 style="font-size:22px;font-weight:700;color:{color};margin:0 0 12px;">{title}</h1>
    <p style="font-size:14px;color:#7d8590;line-height:1.6;margin:0 0 24px;">{body}</p>
    <a
      href="/dashboard"
      style="background:#21262d;color:#e6edf3;border:1px solid rgba(255,255,255,0.1);
             border-radius:8px;padding:10px 20px;font-size:13px;text-decoration:none;
             display:inline-block;"
    >Back to Dashboard</a>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Buy scan route
# ---------------------------------------------------------------------------

@router.post("/run-buy-scan")
def run_buy_scan(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Scan the watchlist and generate high-conviction BUY proposals."""
    settings = get_settings()
    advisor = _make_advisor(broker_service)
    alert = _agent.run_buy_scan(broker_service, advisor, settings=settings)

    if alert:
        _send_buy_notifications(alert, settings)
        return {"status": "scan_complete", "alert": alert}
    return {"status": "no_candidates", "message": "No high-conviction buy candidates found."}


@router.post("/run-sell-scan")
def run_sell_scan(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Scan portfolio for high-conviction SELL opportunities."""
    settings = get_settings()
    advisor = _make_advisor(broker_service)
    alert = _agent.run_sell_scan(broker_service, advisor, settings=settings)

    if alert:
        _send_sell_notifications(alert, settings)
        return {"status": "scan_complete", "alert": alert}
    return {"status": "no_candidates", "message": "No high-conviction exit candidates found."}


def run_scheduled_sell_scan() -> dict | None:
    """Called by the background scheduler — builds its own services."""
    from schwab_trader.server.dependencies import get_broker_service as _gbk

    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    try:
        broker_service = _gbk()
        advisor = AdvisorService(broker_service=broker_service, api_key=settings.anthropic_api_key)
        alert = _agent.run_sell_scan(broker_service, advisor, settings=settings)
        if alert:
            _send_sell_notifications(alert, settings)
        return alert
    except Exception:
        logger.exception("Scheduled sell scan failed")
        return None


def run_scheduled_buy_scan() -> dict | None:
    """Called by the background scheduler — builds its own services."""
    from schwab_trader.server.dependencies import get_broker_service as _gbk

    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    try:
        broker_service = _gbk()
        advisor = AdvisorService(broker_service=broker_service, api_key=settings.anthropic_api_key)
        alert = _agent.run_buy_scan(broker_service, advisor, settings=settings)
        if alert:
            _send_buy_notifications(alert, settings)
        return alert
    except Exception:
        logger.exception("Scheduled buy scan failed")
        return None


# ---------------------------------------------------------------------------
# Insider / Congressional trading feed
# ---------------------------------------------------------------------------

@router.get("/insider-feed")
def get_insider_feed(symbols: str = "") -> dict:
    """Fetch corporate insider transactions + congressional trades for given symbols.

    ?symbols=NVDA,AMD,TSLA  — comma-separated watchlist.
    If symbols is empty, uses the configured buy_scan_watchlist.
    Returns buys AND sells so the user can see the full picture.
    """
    import urllib.request
    import json as _json
    from datetime import datetime, timedelta
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, as_completed

    settings = get_settings()
    if symbols.strip():
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        sym_list = [s.strip().upper() for s in settings.buy_scan_watchlist.split(",") if s.strip()]

    symbol_set = set(sym_list)
    cutoff_dt = datetime.now() - timedelta(days=180)

    # ── Corporate insiders (SEC EDGAR Form 4 — primary source) ──────────────
    corporate: list[dict] = []
    try:
        from schwab_trader.edgar.service import get_form4_trades
        edgar_map = get_form4_trades(sym_list, days=180)
        for sym, trades in edgar_map.items():
            for t in trades:
                corporate.append({
                    "symbol": sym,
                    "source": "SEC EDGAR Form 4",
                    "name": str(t.get("insider", ""))[:80],
                    "title": str(t.get("title", ""))[:60],
                    "type": t.get("transaction_type", "buy"),
                    "shares": t.get("shares", 0),
                    "value": t.get("value", 0),
                    "price": t.get("price", 0),
                    "date": t.get("date", ""),
                    "party": "",
                    "chamber": "",
                })
    except Exception as _edgar_exc:
        logger.warning("EDGAR Form 4 feed failed, falling back to yfinance: %s", _edgar_exc)
        def _fetch_corp(sym: str) -> tuple[str, list]:
            trades = []
            try:
                df = yf.Ticker(sym).insider_transactions
                if df is None or df.empty:
                    return sym, []
                for _, row in df.iterrows():
                    tx_date = row.get("Start Date") or row.get("startDate")
                    if tx_date is None:
                        continue
                    if hasattr(tx_date, "to_pydatetime"):
                        tx_date = tx_date.to_pydatetime().replace(tzinfo=None)
                    if isinstance(tx_date, str):
                        try:
                            tx_date = datetime.strptime(tx_date[:10], "%Y-%m-%d")
                        except Exception:
                            continue
                    if tx_date < cutoff_dt:
                        continue
                    text = str(row.get("Text") or row.get("text") or "")
                    tx_type = "sell" if ("sale" in text.lower() or "sell" in text.lower()) else "buy"
                    trades.append({
                        "symbol": sym,
                        "source": "yfinance",
                        "name": str(row.get("Insider") or row.get("insider") or "")[:80],
                        "title": str(row.get("Relationship") or row.get("relationship") or "")[:60],
                        "type": tx_type,
                        "shares": int(row.get("Shares") or row.get("shares") or 0),
                        "value": int(row.get("Value") or row.get("value") or 0),
                        "date": tx_date.strftime("%Y-%m-%d"),
                        "party": "",
                        "chamber": "",
                    })
            except Exception:
                pass
            return sym, trades[:10]

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_corp, s): s for s in sym_list}
            for fut in as_completed(futures):
                _, trades = fut.result()
                corporate.extend(trades)

    # ── Congressional trades (Quiver Quantitative API) ───────────────────────
    congressional: list[dict] = []
    quiver_key = settings.quiver_quant_api_key.strip()

    if quiver_key:
        import requests as _requests

        def _fetch_quiver(sym: str) -> list[dict]:
            """Fetch congressional trades for one ticker from Quiver Quant."""
            trades = []
            try:
                url = f"https://api.quiverquant.com/beta/historical/congresstrading/{sym}"
                resp = _requests.get(
                    url,
                    headers={
                        "Authorization": f"Token {quiver_key}",
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json",
                    },
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.debug("Quiver Quant %s: HTTP %s", sym, resp.status_code)
                    return []
                for tx in resp.json():
                    raw_date = tx.get("Date") or tx.get("ReportDate") or ""
                    try:
                        tx_date = datetime.strptime(raw_date[:10], "%Y-%m-%d")
                    except Exception:
                        continue
                    if tx_date < cutoff_dt:
                        continue
                    tx_type_raw = (tx.get("Transaction") or "").lower()
                    if "purchase" in tx_type_raw or "buy" in tx_type_raw:
                        tx_type = "buy"
                    elif "sale" in tx_type_raw or "sell" in tx_type_raw:
                        tx_type = "sell"
                    else:
                        continue
                    trades.append({
                        "symbol": sym,
                        "source": "congressional",
                        "name": str(tx.get("Representative") or "")[:80],
                        "title": str(tx.get("Chamber") or "Congress")[:20],
                        "type": tx_type,
                        "shares": 0,
                        "value": 0,
                        "date": raw_date[:10],
                        "party": str(tx.get("Party") or "")[:10],
                        "chamber": str(tx.get("Chamber") or "").lower(),
                        "amount_range": str(tx.get("Range") or tx.get("Amount") or "")[:30],
                        "state": str(tx.get("State") or "")[:5],
                    })
            except Exception as exc:
                logger.debug("Quiver Quant %s: %s", sym, exc)
            return trades

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_fetch_quiver, s): s for s in sym_list}
            for fut in as_completed(futures):
                congressional.extend(fut.result())

    # Sort all by date descending
    all_trades = sorted(corporate + congressional, key=lambda x: x["date"], reverse=True)
    return {
        "trades": all_trades,
        "corporate_count": len(corporate),
        "congressional_count": len(congressional),
        "congressional_enabled": bool(quiver_key),
    }


# ---------------------------------------------------------------------------
# Thesis tracker endpoints
# ---------------------------------------------------------------------------

@router.get("/thesis")
def get_thesis() -> dict:
    """Return all tracked thesis entries sorted by severity."""
    from schwab_trader.thesis import service as _thesis
    _thesis.seed_from_alerts(_store)
    return {"theses": _thesis.get_all()}


@router.post("/run-thesis-check")
def run_thesis_check(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> dict:
    """Manually trigger a thesis check for all tracked positions."""
    from schwab_trader.thesis import service as _thesis
    settings = get_settings()
    if not settings.anthropic_api_key:
        return {"status": "error", "message": "ANTHROPIC_API_KEY not configured"}
    advisor = AdvisorService(broker_service=broker_service, api_key=settings.anthropic_api_key)
    _thesis.seed_from_alerts(_store)
    updated = _thesis.check_all(broker_service, advisor)
    return {"status": "complete", "checked": len(updated), "theses": updated}


# ---------------------------------------------------------------------------
# Trade approval router (registered at app root — no /api/v1/agent prefix)
# ---------------------------------------------------------------------------

trade_router = APIRouter()


class TradeApprovalRequest(BaseModel):
    """Confirmation payload for browser-driven approval."""

    confirm_token: str


def _proposal_review_html(proposal: dict, confirm_token: str) -> str:
    order_desc = (
        f"{proposal['action']} {int(proposal['quantity'])} {proposal['symbol']} "
        f"@ ${float(proposal['limit_price']):.2f} LIMIT"
        if proposal.get("order_type") == "LIMIT" and proposal.get("limit_price") is not None
        else f"{proposal['action']} {int(proposal['quantity'])} {proposal['symbol']} @ MARKET"
    )
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Review Before Execution</title>
</head>
<body
  style="margin:0;padding:0;background:#0d1117;color:#e6edf3;
         font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         display:flex;align-items:center;justify-content:center;min-height:100vh;"
>
  <div
    style="background:#161b22;border:1px solid rgba(255,255,255,0.08);border-radius:16px;
           padding:28px;width:min(520px,92vw);box-shadow:0 24px 80px rgba(0,0,0,0.45);"
  >
    <div
      style="font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
             color:#7d8590;margin-bottom:10px;"
    >Review Before Execution</div>
    <h1 style="margin:0 0 10px;font-size:24px;letter-spacing:-0.03em;">Confirm Live Order</h1>
    <div style="font-size:15px;color:#e6edf3;margin-bottom:14px;">{order_desc}</div>
    <div
      style="background:rgba(248,81,73,0.08);border:1px solid rgba(248,81,73,0.25);
             border-radius:12px;padding:14px 16px;font-size:13px;line-height:1.6;
             color:#fca5a5;margin-bottom:16px;"
    >
      This page does not place an order until you click the confirmation button below.
    </div>
    <div
      style="background:#0d1117;border-radius:12px;padding:14px 16px;font-size:13px;
             line-height:1.65;color:#c9d1d9;margin-bottom:18px;"
    >{proposal.get('reasoning', '')}</div>
    <div style="display:flex;gap:10px;">
      <button
        id="confirmBtn"
        onclick="confirmApproval()"
        style="flex:1;background:#238636;color:#fff;border:none;border-radius:10px;
               padding:12px 18px;font-size:14px;font-weight:700;cursor:pointer;"
      >Place Order</button>
      <a
        href="/dashboard"
        style="flex:1;text-align:center;background:#21262d;color:#e6edf3;
               border:1px solid rgba(255,255,255,0.12);border-radius:10px;
               padding:12px 18px;font-size:14px;text-decoration:none;"
      >Cancel</a>
    </div>
    <div id="status" style="margin-top:14px;font-size:13px;color:#7d8590;"></div>
  </div>
  <script>
    window.__TRADE_CONFIRM__ = {{"confirm_token":"{confirm_token}"}};
    async function confirmApproval() {{
      const btn = document.getElementById('confirmBtn');
      const status = document.getElementById('status');
      btn.disabled = true;
      btn.textContent = 'Placing...';
      status.textContent = 'Running risk checks and Schwab preview...';
      try {{
        const response = await fetch(window.location.pathname, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(window.__TRADE_CONFIRM__),
        }});
        const html = await response.text();
        document.open();
        document.write(html);
        document.close();
      }} catch (error) {{
        status.textContent = 'Could not submit confirmation. Please try again.';
        btn.disabled = false;
        btn.textContent = 'Place Order';
      }}
    }}
  </script>
</body>
</html>"""


@trade_router.get("/trade/approve/{token}", response_class=HTMLResponse)
def approve_by_token(
    token: str,
) -> HTMLResponse:
    """Render a human confirmation page for a tokenized approval link."""
    proposal, _ = _store.find_proposal_by_token(token)
    if not proposal:
        return HTMLResponse(
            _result_html(
                "Link Not Found",
                "This approval link is invalid or has already been used.",
                success=False,
            ),
            status_code=404,
        )

    expires_raw = proposal.get("token_expires_at", "")
    if expires_raw:
        try:
            if datetime.now(UTC) > datetime.fromisoformat(expires_raw):
                return HTMLResponse(
                    _result_html(
                        "Link Expired",
                        "This approval link expired 24 hours after it was sent.",
                        success=False,
                    ),
                    status_code=410,
                )
        except Exception:
            pass

    if proposal.get("status") != "pending":
        status_word = proposal.get("status", "acted on")
        return HTMLResponse(
            _result_html(
                "Already Acted",
                f"This proposal has already been {status_word}.",
            )
        )

    confirm_token = _store.issue_confirmation_token(proposal["id"])
    if not confirm_token:
        return HTMLResponse(
            _result_html(
                "Link Not Found",
                "This approval link is invalid or has already been used.",
                success=False,
            ),
            status_code=404,
        )
    return HTMLResponse(_proposal_review_html(proposal, confirm_token))


@trade_router.post("/trade/approve/{token}", response_class=HTMLResponse)
def approve_by_token_post(
    token: str,
    payload: Annotated[TradeApprovalRequest, Body()],
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> HTMLResponse:
    """Execute a previously reviewed approval link after explicit confirmation."""

    proposal, _ = _store.find_proposal_by_token(token)
    if not proposal:
        return HTMLResponse(
            _result_html(
                "Link Not Found",
                "This approval link is invalid or has already been used.",
                success=False,
            ),
            status_code=404,
        )
    if proposal.get("status") != "pending":
        status_word = proposal.get("status", "acted on")
        return HTMLResponse(
            _result_html(
                "Already Acted",
                f"This proposal has already been {status_word}.",
            )
        )
    if not _store.consume_confirmation_token(proposal["id"], payload.confirm_token):
        return HTMLResponse(
            _result_html(
                "Confirmation Expired",
                "Reload the approval link and confirm the trade again.",
                success=False,
            ),
            status_code=400,
        )

    try:
        _get_execution_service(broker_service).execute_proposal(proposal, source="approval_link")
    except ProposalExecutionError as exc:
        logger.error("Token approval order failed: %s", exc.detail)
        return HTMLResponse(
            _result_html("Order Failed", exc.detail, success=False),
            status_code=exc.status_code,
        )

    _store.update_proposal_status(proposal["id"], "executed")
    if proposal.get("action") == "BUY" and proposal.get("limit_price"):
        entry = float(proposal["limit_price"])
        _store.set_exit_targets(
            proposal["id"],
            target_price=round(entry * 1.30, 2),
            stop_price=round(entry * 0.85, 2),
        )
    action = proposal.get("action", "BUY")
    price_str = f"@ ${proposal['limit_price']}" if proposal.get("limit_price") else "at market"
    return HTMLResponse(
        _result_html(
            "Trade Executed",
            f"{action} {int(proposal['quantity'])} shares of {proposal['symbol']} "
            f"{price_str} has been placed on your Schwab account.",
        )
    )


@trade_router.get("/trade/deny/{token}", response_class=HTMLResponse)
def deny_by_token(token: str) -> HTMLResponse:
    """One-click trade denial from SMS/email link."""
    proposal, _ = _store.find_proposal_by_token(token)
    if not proposal:
        return HTMLResponse(
            _result_html("Link Not Found", "This link is invalid.", success=False),
            status_code=404,
        )
    if proposal.get("status") == "pending":
        _store.update_proposal_status(proposal["id"], "cancelled")
    action = proposal.get("action", "BUY")
    return HTMLResponse(_result_html(
        "Trade Denied",
        f"The {action} proposal for {proposal.get('symbol', '')} has been cancelled.",
        success=False,
    ))


@router.get("/briefing")
def get_briefing(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
    force: bool = False,
) -> dict:
    """Return (or generate) the daily AI portfolio briefing."""
    if not force:
        cached = _store.get_briefing_cache(max_age_hours=6.0)
        if cached:
            return {"status": "cached", "briefing": cached}

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured.")

    from schwab_trader.advisor.service import AdvisorService as _Adv
    advisor = _Adv(broker_service=broker_service, api_key=settings.anthropic_api_key)
    briefing = _agent.generate_briefing(broker_service, advisor)
    if not briefing:
        raise HTTPException(status_code=500, detail="Briefing generation failed.")

    _store.save_briefing_cache(briefing)
    return {"status": "generated", "briefing": briefing}


@router.post("/mute/{symbol}")
def mute_symbol(symbol: str, days: int = 7) -> dict:
    """Mute alert flags for a symbol for N days."""
    _store.mute_symbol(symbol.upper(), days=days)
    return {"status": "muted", "symbol": symbol.upper(), "days": days}


@router.delete("/mute/{symbol}")
def unmute_symbol(symbol: str) -> dict:
    """Remove a mute for a symbol."""
    _store.unmute_symbol(symbol.upper())
    return {"status": "unmuted", "symbol": symbol.upper()}


@router.get("/muted")
def list_muted() -> dict:
    """Return currently muted symbols with their expiry times."""
    return {"muted": _store.get_muted_symbols()}


@router.get("/status")
def agent_status() -> dict:
    """Return agent configuration status."""
    settings = get_settings()
    alerts = _store.load_all()
    pending = [a for a in alerts if a.get("status") == "pending"]
    return {
        "pending_alerts": len(pending),
        "total_alerts": len(alerts),
        "sms_configured": bool(
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_from_number
            and settings.alert_phone_number
        ),
        "check_interval_minutes": settings.agent_check_interval_minutes,
        "thresholds": {
            "earnings_days": settings.alert_earnings_days,
            "position_down_pct": settings.alert_position_down_pct,
            "day_loss_pct": settings.alert_day_loss_pct,
            "concentration_pct": settings.alert_concentration_pct,
            "gain_alert_pct": settings.alert_gain_pct,
        },
    }


@router.get("/macro")
def get_macro() -> dict:
    """Return current market regime snapshot: VIX, SPY/QQQ vs 200MA, sector ETF performance."""
    try:
        from schwab_trader.agent.tools import ToolExecutor
        from schwab_trader.broker.service import SchwabBrokerService as _BS
        # ToolExecutor only needs broker for stock tools — macro uses yfinance exclusively
        executor = ToolExecutor(broker_service=None)  # type: ignore[arg-type]
        import json
        raw = executor.get_macro_context()
        return json.loads(raw)
    except Exception as exc:
        logger.exception("Macro context fetch failed")
        raise HTTPException(status_code=500, detail=str(exc))
