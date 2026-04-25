"""Home page and setup-status routes."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from schwab_trader.auth.browser_session import COOKIE_NAME, is_valid_session
from schwab_trader.core.settings import get_settings
from schwab_trader.journal.models import JournalOverview
from schwab_trader.server.dependencies import get_journal_store, get_token_store, require_auth


class AppStatusResponse(BaseModel):
    """Current local setup and auth status."""

    oauth_settings_complete: bool
    missing_settings: list[str]
    callback_url: str | None = None
    scope: str
    authenticated: bool
    access_token_expires_at: str | None = None
    journal_overview: JournalOverview


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home() -> RedirectResponse:
    """Redirect root to the trading dashboard."""

    return RedirectResponse("/dashboard", status_code=302)


@router.get("/setup", response_class=HTMLResponse)
def setup_page(
    session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> HTMLResponse:
    """Serve the Schwab OAuth setup and auth page."""
    if not session or not is_valid_session(session):
        return RedirectResponse(url="/login", status_code=302)  # type: ignore[return-value]
    return HTMLResponse(_home_html())


@router.get("/dashboard", response_class=HTMLResponse)
def trading_dashboard(
    session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> HTMLResponse:
    """Serve the live trading dashboard — redirect to login if unauthenticated."""

    if not session or not is_valid_session(session):
        return RedirectResponse(url="/login", status_code=302)  # type: ignore[return-value]
    return HTMLResponse(
        _live_dashboard_html(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/customize", response_class=HTMLResponse)
def customize_page(
    session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> HTMLResponse:
    """Serve the dashboard customization page."""
    if not session or not is_valid_session(session):
        return RedirectResponse(url="/login", status_code=302)  # type: ignore[return-value]
    return HTMLResponse(_customize_html())


@router.get("/api/v1/settings")
def get_current_settings() -> dict:
    """Return current agent threshold settings."""
    s = get_settings()
    return {
        # Connection status (secrets never returned — just whether configured)
        "schwab_configured":       bool(s.schwab_app_key and s.schwab_app_secret),
        "schwab_callback_url":     s.schwab_callback_url or "",
        "schwab_scope":            s.schwab_scope,
        "anthropic_configured":    bool(s.anthropic_api_key),
        "quiver_quant_configured": bool(s.quiver_quant_api_key),
        "fred_configured":         bool(s.fred_api_key),
        "twilio_configured":       bool(s.twilio_account_sid and s.twilio_auth_token),
        "twilio_from_number":      s.twilio_from_number,
        # Notifications
        "alert_phone_number":                    s.alert_phone_number,
        "dashboard_url":                         s.dashboard_url,
        "email_smtp_host":                       s.email_smtp_host,
        "email_smtp_port":                       s.email_smtp_port,
        "email_smtp_user":                       s.email_smtp_user,
        "alert_email_address":                   s.alert_email_address,
        # Risk scan
        "alert_earnings_days":                   s.alert_earnings_days,
        "alert_position_down_pct":               s.alert_position_down_pct,
        "alert_day_loss_pct":                    s.alert_day_loss_pct,
        "alert_concentration_pct":               s.alert_concentration_pct,
        "alert_gain_pct":                        s.alert_gain_pct,
        "agent_check_interval_minutes":          s.agent_check_interval_minutes,
        # Opportunity scan
        "buy_scan_budget":                       s.buy_scan_budget,
        "buy_scan_interval_hours":               s.buy_scan_interval_hours,
        "buy_scan_max_proposals":                s.buy_scan_max_proposals,
        "buy_scan_watchlist":                    s.buy_scan_watchlist,
        "email_min_upside_pct":                  s.email_min_upside_pct,
        # Safety guardrails
        "live_order_kill_switch":                        s.live_order_kill_switch,
        "live_order_max_daily_loss_dollars":             s.live_order_max_daily_loss_dollars,
        "live_order_max_order_notional_dollars":         s.live_order_max_order_notional_dollars,
        "live_order_max_open_positions":                 s.live_order_max_open_positions,
        "live_order_max_single_trade_risk_dollars":      s.live_order_max_single_trade_risk_dollars,
        "live_order_max_symbol_allocation_pct":          s.live_order_max_symbol_allocation_pct,
        "live_order_require_stop_loss_for_entries":      s.live_order_require_stop_loss_for_entries,
        "regime_enabled":                                s.regime_enabled,
    }


@router.post("/api/v1/settings", dependencies=[Depends(require_auth)])
def update_settings(payload: dict) -> dict:
    """Persist threshold overrides to the .env file and clear the settings cache."""
    from pathlib import Path as _Path

    env_path = _Path(__file__).resolve().parents[4] / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []

    key_map = {
        # Connections
        "schwab_app_key":                         "SCHWAB_TRADER_SCHWAB_APP_KEY",
        "schwab_app_secret":                      "SCHWAB_TRADER_SCHWAB_APP_SECRET",
        "schwab_callback_url":                    "SCHWAB_TRADER_SCHWAB_CALLBACK_URL",
        "anthropic_api_key":                      "SCHWAB_TRADER_ANTHROPIC_API_KEY",
        "quiver_quant_api_key":                   "SCHWAB_TRADER_QUIVER_QUANT_API_KEY",
        "fred_api_key":                           "SCHWAB_TRADER_FRED_API_KEY",
        "twilio_account_sid":                     "SCHWAB_TRADER_TWILIO_ACCOUNT_SID",
        "twilio_auth_token":                      "SCHWAB_TRADER_TWILIO_AUTH_TOKEN",
        "twilio_from_number":                     "SCHWAB_TRADER_TWILIO_FROM_NUMBER",
        # Notifications
        "alert_phone_number":                     "SCHWAB_TRADER_ALERT_PHONE_NUMBER",
        "dashboard_url":                          "SCHWAB_TRADER_DASHBOARD_URL",
        "email_smtp_host":                        "SCHWAB_TRADER_EMAIL_SMTP_HOST",
        "email_smtp_port":                        "SCHWAB_TRADER_EMAIL_SMTP_PORT",
        "email_smtp_user":                        "SCHWAB_TRADER_EMAIL_SMTP_USER",
        "email_smtp_password":                    "SCHWAB_TRADER_EMAIL_SMTP_PASSWORD",
        "alert_email_address":                    "SCHWAB_TRADER_ALERT_EMAIL_ADDRESS",
        # Risk scan
        "alert_earnings_days":                    "SCHWAB_TRADER_ALERT_EARNINGS_DAYS",
        "alert_position_down_pct":                "SCHWAB_TRADER_ALERT_POSITION_DOWN_PCT",
        "alert_day_loss_pct":                     "SCHWAB_TRADER_ALERT_DAY_LOSS_PCT",
        "alert_concentration_pct":                "SCHWAB_TRADER_ALERT_CONCENTRATION_PCT",
        "alert_gain_pct":                         "SCHWAB_TRADER_ALERT_GAIN_PCT",
        "agent_check_interval_minutes":           "SCHWAB_TRADER_AGENT_CHECK_INTERVAL_MINUTES",
        # Opportunity scan
        "buy_scan_budget":                        "SCHWAB_TRADER_BUY_SCAN_BUDGET",
        "buy_scan_interval_hours":                "SCHWAB_TRADER_BUY_SCAN_INTERVAL_HOURS",
        "buy_scan_max_proposals":                 "SCHWAB_TRADER_BUY_SCAN_MAX_PROPOSALS",
        "buy_scan_watchlist":                     "SCHWAB_TRADER_BUY_SCAN_WATCHLIST",
        "email_min_upside_pct":                   "SCHWAB_TRADER_EMAIL_MIN_UPSIDE_PCT",
        # Safety guardrails
        "live_order_kill_switch":                        "SCHWAB_TRADER_LIVE_ORDER_KILL_SWITCH",
        "live_order_max_daily_loss_dollars":             "SCHWAB_TRADER_LIVE_ORDER_MAX_DAILY_LOSS_DOLLARS",
        "live_order_max_order_notional_dollars":         "SCHWAB_TRADER_LIVE_ORDER_MAX_ORDER_NOTIONAL_DOLLARS",
        "live_order_max_open_positions":                 "SCHWAB_TRADER_LIVE_ORDER_MAX_OPEN_POSITIONS",
        "live_order_max_single_trade_risk_dollars":      "SCHWAB_TRADER_LIVE_ORDER_MAX_SINGLE_TRADE_RISK_DOLLARS",
        "live_order_max_symbol_allocation_pct":          "SCHWAB_TRADER_LIVE_ORDER_MAX_SYMBOL_ALLOCATION_PCT",
        "live_order_require_stop_loss_for_entries":      "SCHWAB_TRADER_LIVE_ORDER_REQUIRE_STOP_LOSS_FOR_ENTRIES",
        "regime_enabled":                                "SCHWAB_TRADER_REGIME_ENABLED",
    }

    updated: set[str] = set()
    new_lines = []
    for line in lines:
        replaced = False
        for field, env_key in key_map.items():
            if field in payload and line.startswith(env_key + "="):
                new_lines.append(f"{env_key}={payload[field]}")
                updated.add(env_key)
                replaced = True
                break
        if not replaced:
            new_lines.append(line)

    # Append any keys that weren't already in the file
    for field, env_key in key_map.items():
        if field in payload and env_key not in updated:
            new_lines.append(f"{env_key}={payload[field]}")

    env_path.write_text("\n".join(new_lines) + "\n")
    get_settings.cache_clear()
    return {"status": "saved"}


@router.get("/api/v1/app/status", response_model=AppStatusResponse)
def app_status(
    store: Annotated[object, Depends(get_journal_store)],
    token_store: Annotated[object, Depends(get_token_store)],
) -> AppStatusResponse:
    """Return configuration, auth, and local journal status."""

    settings = get_settings()
    missing_settings = [
        name
        for name, value in (
            ("SCHWAB_TRADER_SCHWAB_APP_KEY", settings.schwab_app_key),
            ("SCHWAB_TRADER_SCHWAB_APP_SECRET", settings.schwab_app_secret),
            ("SCHWAB_TRADER_SCHWAB_CALLBACK_URL", settings.schwab_callback_url),
        )
        if not value
    ]
    token = token_store.load()
    overview = store.get_overview()
    # A token on disk is only "authenticated" if the Schwab refresh token
    # hasn't expired. If refresh_token_created_at is unknown (old token), we
    # fall back to trusting the file exists.
    token_usable = False
    if token is not None:
        hours = token.refresh_token_hours_remaining()
        token_usable = hours is None or hours > 0
    return AppStatusResponse(
        oauth_settings_complete=not missing_settings,
        missing_settings=missing_settings,
        callback_url=settings.schwab_callback_url,
        scope=settings.schwab_scope,
        authenticated=token_usable,
        access_token_expires_at=token.access_token_expires_at.isoformat() if token else None,
        journal_overview=overview,
    )


def _customize_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Settings — Schwab Trader</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%231e3a5f'/%3E%3Cpolyline points='4,22 10,16 16,19 22,10 28,6' fill='none' stroke='%2322c55e' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg:         #080B10;
      --surface:    #0E1318;
      --surface2:   #141A22;
      --surface3:   #1C242E;
      --ink:        #E8EDF5;
      --muted:      #7A8599;
      --dim:        #444D5E;
      --line:       rgba(240,246,252,0.07);
      --line2:      rgba(240,246,252,0.12);
      --accent:     #2563EB;
      --accent-soft:rgba(37,99,235,0.10);
      --green:      #22C55E;
      --green-soft: rgba(34,197,94,0.10);
      --red:        #EF4444;
      --red-soft:   rgba(239,68,68,0.10);
      --amber:      #F59E0B;
      --radius:     8px;
    }
    *, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
    body {
      background:var(--bg); color:var(--ink);
      font-family:'Inter',ui-sans-serif,system-ui,-apple-system,sans-serif;
      font-size:14px; min-height:100vh; -webkit-font-smoothing:antialiased;
    }
    /* ── Top bar ── */
    .topbar {
      display:flex; align-items:center; justify-content:space-between;
      padding:14px 28px; background:var(--surface); border-bottom:1px solid var(--line);
      position:sticky; top:0; z-index:10;
    }
    .topbar-brand { display:flex; align-items:center; gap:10px; text-decoration:none; }
    .topbar-logo {
      width:28px; height:28px; border-radius:7px; flex-shrink:0;
      background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);
      display:flex; align-items:center; justify-content:center;
    }
    .topbar-logo svg { width:14px; height:14px; color:#fff; }
    .topbar-name { font-size:13px; font-weight:700; letter-spacing:-0.02em; color:var(--ink); }
    .back-link {
      display:flex; align-items:center; gap:5px; color:var(--muted);
      text-decoration:none; font-size:13px; font-weight:500;
      padding:6px 12px; border-radius:7px; border:1px solid var(--line);
      transition:all .15s;
    }
    .back-link:hover { color:var(--ink); border-color:rgba(255,255,255,.14); background:var(--surface2); }
    /* ── Layout ── */
    .settings-shell { display:flex; min-height:calc(100vh - 57px); }
    .settings-nav {
      width:200px; flex-shrink:0; padding:20px 12px;
      border-right:1px solid var(--line); position:sticky; top:57px;
      height:calc(100vh - 57px); overflow-y:auto;
    }
    .snav-item {
      display:flex; align-items:center; gap:8px;
      padding:7px 10px; border-radius:7px; font-size:13px; font-weight:500;
      color:var(--muted); cursor:pointer; text-decoration:none;
      transition:background .1s, color .1s; margin-bottom:2px;
    }
    .snav-item:hover { background:rgba(255,255,255,.05); color:var(--ink); }
    .snav-item.active { background:var(--accent-soft,rgba(37,99,235,.10)); color:var(--accent); font-weight:600; }
    .snav-dot { width:6px; height:6px; border-radius:50%; background:var(--muted); flex-shrink:0; }
    .snav-item.active .snav-dot { background:var(--accent); box-shadow:0 0 5px var(--accent); }
    .settings-body { flex:1; padding:28px 36px 80px; max-width:780px; }
    /* ── Sections ── */
    .settings-section {
      margin-bottom:40px; scroll-margin-top:80px;
    }
    .section-head {
      display:flex; align-items:center; gap:10px;
      padding-bottom:12px; border-bottom:1px solid var(--line); margin-bottom:18px;
    }
    .section-icon {
      width:32px; height:32px; border-radius:8px; flex-shrink:0;
      display:flex; align-items:center; justify-content:center;
    }
    .section-icon svg { width:15px; height:15px; }
    .section-title { font-size:15px; font-weight:700; letter-spacing:-0.02em; color:var(--ink); }
    .section-sub { font-size:12px; color:var(--muted); margin-top:2px; }
    /* ── Fields ── */
    .field-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .field-grid.col1 { grid-template-columns:1fr; }
    .field {
      background:var(--surface); border:1px solid var(--line);
      border-radius:10px; padding:14px 16px;
      transition:border-color .15s;
    }
    .field:focus-within { border-color:var(--accent); }
    .field-label {
      font-size:10.5px; font-weight:700; text-transform:uppercase;
      letter-spacing:.07em; color:var(--muted); margin-bottom:8px; display:block;
    }
    .field-row { display:flex; align-items:center; gap:8px; }
    .field-prefix { font-size:13px; color:var(--muted); flex-shrink:0; }
    .finput {
      background:var(--surface2); border:1px solid var(--line); color:var(--ink);
      border-radius:7px; padding:7px 10px; font-size:14px; font-weight:500;
      font-family:inherit; outline:none; transition:border-color .15s;
    }
    .finput:focus { border-color:var(--accent); }
    .finput-num { width:88px; text-align:right; }
    .finput-full { width:100%; }
    .field-unit { font-size:12px; color:var(--muted); white-space:nowrap; }
    .field-hint { font-size:11.5px; color:var(--muted); margin-top:7px; line-height:1.45; }
    /* ── Toggle (kill switch) ── */
    .toggle-field {
      background:var(--surface); border:1px solid var(--line);
      border-radius:10px; padding:14px 16px;
      display:flex; align-items:center; justify-content:space-between; gap:16px;
    }
    .toggle-field.on { border-color:rgba(239,68,68,.3); background:var(--red-soft); }
    .toggle-text { flex:1; min-width:0; }
    .toggle-label { font-size:14px; font-weight:600; color:var(--ink); }
    .toggle-desc  { font-size:12px; color:var(--muted); margin-top:3px; line-height:1.4; }
    .toggle-switch { position:relative; width:44px; height:24px; flex-shrink:0; }
    .toggle-switch input { opacity:0; width:0; height:0; }
    .toggle-track {
      position:absolute; inset:0; border-radius:99px;
      background:var(--surface3); border:1px solid var(--line);
      cursor:pointer; transition:.2s;
    }
    .toggle-track::before {
      content:''; position:absolute; width:18px; height:18px;
      left:2px; top:2px; border-radius:50%;
      background:var(--muted); transition:.2s;
    }
    .toggle-switch input:checked + .toggle-track { background:var(--red); border-color:var(--red); }
    .toggle-switch input:checked + .toggle-track::before { transform:translateX(20px); background:white; }
    .toggle-switch.green input:checked + .toggle-track { background:var(--green); border-color:var(--green); }
    /* ── Status banner ── */
    .status-banner {
      padding:10px 14px; border-radius:8px; font-size:13px; font-weight:500;
      display:none; margin-bottom:16px; align-items:center; gap:8px;
    }
    .status-banner.success { display:flex; background:var(--green-soft); color:var(--green); border:1px solid rgba(34,197,94,.2); }
    .status-banner.error   { display:flex; background:var(--red-soft);   color:var(--red);   border:1px solid rgba(239,68,68,.2); }
    /* ── Save bar ── */
    .save-bar {
      position:fixed; bottom:0; left:200px; right:0;
      padding:14px 36px; background:var(--surface);
      border-top:1px solid var(--line);
      display:flex; align-items:center; gap:12px; z-index:9;
    }
    .btn-save {
      background:var(--accent); color:white; border:none; border-radius:8px;
      padding:10px 26px; font-size:13px; font-weight:700; cursor:pointer;
      font-family:inherit; transition:opacity .15s, transform .1s; letter-spacing:-.01em;
    }
    .btn-save:hover { opacity:.87; }
    .btn-save:active { transform:scale(.97); }
    .btn-save:disabled { opacity:.35; cursor:not-allowed; }
    .save-msg { font-size:13px; color:var(--green); font-weight:500; opacity:0; transition:opacity .3s; }
    .save-err { font-size:13px; color:var(--red); font-weight:500; opacity:0; transition:opacity .3s; }
    @media(max-width:700px) {
      .settings-nav { display:none; }
      .settings-body { padding:20px 18px 80px; }
      .field-grid { grid-template-columns:1fr; }
      .save-bar { left:0; padding:14px 18px; }
    }
  </style>
</head>
<body>
<div class="topbar">
  <a class="topbar-brand" href="/dashboard">
    <div class="topbar-logo">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
        <polyline points="16 7 22 7 22 13"/>
      </svg>
    </div>
    <span class="topbar-name">Schwab Trader</span>
  </a>
  <a class="back-link" href="/dashboard">&#8592; Back to Dashboard</a>
</div>

<div class="settings-shell">
  <!-- Left nav -->
  <nav class="settings-nav">
    <a class="snav-item active" href="#connections" onclick="navClick(event,this)">
      <span class="snav-dot"></span> Connections
    </a>
    <a class="snav-item" href="#notifications" onclick="navClick(event,this)">
      <span class="snav-dot"></span> Notifications
    </a>
    <a class="snav-item" href="#risk-scan" onclick="navClick(event,this)">
      <span class="snav-dot"></span> Risk Scan
    </a>
    <a class="snav-item" href="#opp-scan" onclick="navClick(event,this)">
      <span class="snav-dot"></span> Opportunity Scan
    </a>
    <a class="snav-item" href="#guardrails" onclick="navClick(event,this)">
      <span class="snav-dot"></span> Safety Guardrails
    </a>
  </nav>

  <div class="settings-body" id="settingsBody">
    <div id="statusBanner" class="status-banner"></div>

    <!-- ── Connections ── -->
    <div class="settings-section" id="connections">
      <div class="section-head">
        <div class="section-icon" style="background:rgba(37,99,235,.10);">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
          </svg>
        </div>
        <div>
          <div class="section-title">Connections</div>
          <div class="section-sub">API credentials for Schwab, AI, and SMS services</div>
        </div>
      </div>
      <div class="field-grid">
        <div class="field">
          <label class="field-label">Schwab App Key</label>
          <div class="field-row">
            <input type="password" id="f_schwab_key" class="finput finput-full" placeholder="Leave blank to keep current value"/>
          </div>
          <div class="field-hint">OAuth client ID from developer.schwab.com</div>
        </div>
        <div class="field">
          <label class="field-label">Schwab App Secret</label>
          <div class="field-row">
            <input type="password" id="f_schwab_secret" class="finput finput-full" placeholder="Leave blank to keep current value"/>
          </div>
          <div class="field-hint">OAuth client secret from developer.schwab.com</div>
        </div>
        <div class="field" style="grid-column:span 2;">
          <label class="field-label">Schwab Callback URL</label>
          <div class="field-row">
            <input type="url" id="f_schwab_callback" class="finput finput-full" placeholder="https://127.0.0.1:8182"/>
          </div>
          <div class="field-hint">Must match exactly what is registered in your Schwab app settings.</div>
        </div>
        <div class="field" style="grid-column:span 2;">
          <label class="field-label">Anthropic API Key</label>
          <div class="field-row">
            <input type="password" id="f_anthropic_key" class="finput finput-full" placeholder="Leave blank to keep current value"/>
          </div>
          <div class="field-hint">Powers the AI risk and opportunity analysis. Get yours at console.anthropic.com.</div>
        </div>
        <div class="field" style="grid-column:span 2;">
          <label class="field-label">Quiver Quant API Key <span style="font-size:11px;color:var(--text-muted);font-weight:400;">(optional — enables congressional trading tab)</span></label>
          <div class="field-row">
            <input type="password" id="f_quiver_key" class="finput finput-full" placeholder="Free key at quiverquant.com — shows Pelosi, all House/Senate trades"/>
          </div>
          <div class="field-hint">Sign up free at <strong>quiverquant.com</strong>, go to API, copy your token. Enables the Insiders tab congressional data.</div>
        </div>
        <div class="field" style="grid-column:span 2;">
          <label class="field-label">FRED API Key <span style="font-size:11px;color:var(--text-muted);font-weight:400;">(optional — adds Fed rate, CPI, yield curve to macro context)</span></label>
          <div class="field-row">
            <input type="password" id="f_fred_key" class="finput finput-full" placeholder="Free key at fred.stlouisfed.org — Fed funds rate, CPI, yield curve"/>
          </div>
          <div class="field-hint">Free at <strong>fred.stlouisfed.org/docs/api/api_key.html</strong>. Adds real macro data (Fed rate, CPI, PCE, yield curve) to the AI buy scan context.</div>
        </div>
        <div class="field">
          <label class="field-label">Twilio Account SID</label>
          <div class="field-row">
            <input type="password" id="f_twilio_sid" class="finput finput-full" placeholder="Leave blank to keep current value"/>
          </div>
          <div class="field-hint">Found in your Twilio console dashboard.</div>
        </div>
        <div class="field">
          <label class="field-label">Twilio Auth Token</label>
          <div class="field-row">
            <input type="password" id="f_twilio_token" class="finput finput-full" placeholder="Leave blank to keep current value"/>
          </div>
          <div class="field-hint">Found in your Twilio console dashboard.</div>
        </div>
        <div class="field" style="grid-column:span 2;">
          <label class="field-label">Twilio From Number</label>
          <div class="field-row">
            <input type="tel" id="f_twilio_from" class="finput finput-full" placeholder="+15551234567"/>
          </div>
          <div class="field-hint">The Twilio phone number that sends SMS alerts. E.164 format.</div>
        </div>
      </div>
    </div>

    <!-- ── Notifications ── -->
    <div class="settings-section" id="notifications">
      <div class="section-head">
        <div class="section-icon" style="background:rgba(37,99,235,.10);">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.36 12 19.79 19.79 0 0 1 1.15 3.18 2 2 0 0 1 3.12 1h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.09 8.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 21 16z"/>
          </svg>
        </div>
        <div>
          <div class="section-title">Notifications</div>
          <div class="section-sub">Where alerts and trade ideas are delivered for review</div>
        </div>
      </div>
      <div class="field-grid col1" style="margin-bottom:12px;">
        <div class="field">
          <label class="field-label">SMS Phone Number</label>
          <div class="field-row">
            <input type="tel" id="f_phone" class="finput finput-full" placeholder="+1 555 123 4567"/>
          </div>
          <div class="field-hint">Your mobile number in E.164 format (e.g. +15551234567). Receives a text with approve/deny links for each trade idea.</div>
        </div>
      </div>
      <div class="field-grid col1" style="margin-bottom:12px;">
        <div class="field">
          <label class="field-label">Dashboard URL</label>
          <div class="field-row">
            <input type="url" id="f_dashboard_url" class="finput finput-full" placeholder="http://192.168.1.x:8000"/>
          </div>
          <div class="field-hint">The network address of this app — embedded in SMS approve/deny links. Use your local IP so links work from your phone on the same Wi-Fi, or a public URL if port-forwarded.</div>
        </div>
      </div>
      <div class="field-grid">
        <div class="field">
          <label class="field-label">Alert Email Address</label>
          <div class="field-row">
            <input type="email" id="f_alert_email" class="finput finput-full" placeholder="you@gmail.com"/>
          </div>
          <div class="field-hint">Where HTML approval emails are sent.</div>
        </div>
        <div class="field">
          <label class="field-label">SMTP Host</label>
          <div class="field-row">
            <input type="text" id="f_smtp_host" class="finput finput-full" placeholder="smtp.gmail.com"/>
          </div>
          <div class="field-hint">e.g. smtp.gmail.com for Gmail</div>
        </div>
        <div class="field">
          <label class="field-label">SMTP Port</label>
          <div class="field-row">
            <input type="number" id="f_smtp_port" class="finput finput-num" min="1" max="65535" value="587"/>
          </div>
          <div class="field-hint">587 for TLS · 465 for SSL</div>
        </div>
        <div class="field">
          <label class="field-label">SMTP Username</label>
          <div class="field-row">
            <input type="email" id="f_smtp_user" class="finput finput-full" placeholder="you@gmail.com"/>
          </div>
        </div>
        <div class="field" style="grid-column:span 2;">
          <label class="field-label">SMTP App Password</label>
          <div class="field-row">
            <input type="password" id="f_smtp_pass" class="finput finput-full" placeholder="Leave blank to keep current value"/>
          </div>
          <div class="field-hint">For Gmail: generate an App Password at myaccount.google.com/apppasswords (requires 2FA). Never use your main Gmail password.</div>
        </div>
      </div>
    </div>

    <!-- ── Risk Scan ── -->
    <div class="settings-section" id="risk-scan">
      <div class="section-head">
        <div class="section-icon" style="background:rgba(245,158,11,.10);">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--amber)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
        </div>
        <div>
          <div class="section-title">Risk Scan</div>
          <div class="section-sub">Thresholds that trigger alerts for your held positions</div>
        </div>
      </div>
      <div class="field-grid">
        <div class="field">
          <label class="field-label">Large Winner Alert</label>
          <div class="field-row">
            <input type="number" id="f_gain_pct" class="finput finput-num" min="0" max="500" step="1" value="30"/>
            <span class="field-unit">% gain</span>
          </div>
          <div class="field-hint">Alert when a position's total return exceeds this.</div>
        </div>
        <div class="field">
          <label class="field-label">Drawdown Alert</label>
          <div class="field-row">
            <input type="number" id="f_down_pct" class="finput finput-num" min="0" max="100" step="1" value="8"/>
            <span class="field-unit">% loss</span>
          </div>
          <div class="field-hint">Alert when a position is down more than this from cost basis.</div>
        </div>
        <div class="field">
          <label class="field-label">Daily Portfolio Loss</label>
          <div class="field-row">
            <input type="number" id="f_day_loss" class="finput finput-num" min="0" max="100" step="0.5" value="5"/>
            <span class="field-unit">% in one day</span>
          </div>
          <div class="field-hint">Alert when the whole portfolio drops this much in a single session.</div>
        </div>
        <div class="field">
          <label class="field-label">Concentration Limit</label>
          <div class="field-row">
            <input type="number" id="f_concentration" class="finput finput-num" min="0" max="100" step="1" value="25"/>
            <span class="field-unit">% of portfolio</span>
          </div>
          <div class="field-hint">Alert when one name exceeds this share of total value.</div>
        </div>
        <div class="field">
          <label class="field-label">Earnings Lead Time</label>
          <div class="field-row">
            <input type="number" id="f_earnings_days" class="finput finput-num" min="1" max="30" step="1" value="3"/>
            <span class="field-unit">days before</span>
          </div>
          <div class="field-hint">Warn ahead of earnings for any name you hold.</div>
        </div>
        <div class="field">
          <label class="field-label">Scan Cadence</label>
          <div class="field-row">
            <input type="number" id="f_interval" class="finput finput-num" min="5" max="1440" step="5" value="30"/>
            <span class="field-unit">minutes</span>
          </div>
          <div class="field-hint">How often to automatically re-check your portfolio.</div>
        </div>
      </div>
    </div>

    <!-- ── Opportunity Scan ── -->
    <div class="settings-section" id="opp-scan">
      <div class="section-head">
        <div class="section-icon" style="background:rgba(34,211,90,.10);">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
          </svg>
        </div>
        <div>
          <div class="section-title">Opportunity Scan</div>
          <div class="section-sub">How the AI finds and sizes new trade ideas</div>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px;">
        <div class="field">
          <label class="field-label">Budget per trade</label>
          <div class="field-row">
            <span class="field-prefix">$</span>
            <input type="number" id="f_buy_budget" class="finput" style="width:100px;" min="100" max="100000" step="100" value="2000"/>
          </div>
        </div>
        <div class="field">
          <label class="field-label">Scan every</label>
          <div class="field-row">
            <input type="number" id="f_buy_interval" class="finput finput-num" min="1" max="168" step="1" value="24"/>
            <span class="field-unit">hours</span>
          </div>
        </div>
        <div class="field">
          <label class="field-label">Max ideas per run</label>
          <div class="field-row">
            <input type="number" id="f_buy_max" class="finput finput-num" min="1" max="10" step="1" value="3"/>
          </div>
        </div>
      </div>
      <div class="field" style="margin-bottom:14px;">
        <label class="field-label">Watchlist</label>
        <input type="hidden" id="f_watchlist"/>
        <div id="watchlist-chips" style="display:flex;flex-wrap:wrap;gap:6px;padding:10px 12px;background:var(--surface2,#131920);border:1px solid var(--border,rgba(255,255,255,.08));border-radius:8px;min-height:48px;align-items:flex-start;cursor:text;" onclick="document.getElementById('wl-add-input').focus()">
        </div>
        <div style="display:flex;gap:8px;margin-top:8px;">
          <input id="wl-add-input" type="text" placeholder="Add ticker — e.g. AAPL" class="finput" style="width:200px;text-transform:uppercase;" maxlength="8"
            oninput="this.value=this.value.toUpperCase()"
            onkeydown="if(event.key==='Enter'||event.key===','||event.key===' '){event.preventDefault();wlAddTicker(this.value);this.value='';}"/>
          <button class="btn" type="button" onclick="wlAddTicker(document.getElementById('wl-add-input').value);document.getElementById('wl-add-input').value='';" style="font-size:12px;padding:6px 14px;">Add</button>
        </div>
      </div>
      <div class="field">
        <label class="field-label">Email me when analyst upside exceeds</label>
        <div class="field-row">
          <input type="number" id="f_email_min_upside" class="finput finput-num" min="0" max="100" step="1" value="15"/>
          <span class="field-unit">%</span>
          <span style="font-size:11px;color:var(--muted);margin-left:8px;">Set to 0 to email on every scan.</span>
        </div>
      </div>
    </div>

    <!-- ── Safety Guardrails ── -->
    <div class="settings-section" id="guardrails">
      <div class="section-head">
        <div class="section-icon" style="background:rgba(240,92,82,.10);">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/>
            <line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
        </div>
        <div>
          <div class="section-title">Safety Guardrails</div>
          <div class="section-sub">Hard limits that override AI decisions before any order is placed</div>
        </div>
      </div>
      <div class="field-grid col1" style="margin-bottom:12px;">
        <div class="toggle-field" id="killSwitchRow">
          <div class="toggle-text">
            <div class="toggle-label">Order Kill Switch</div>
            <div class="toggle-desc">When ON, blocks all live order placement regardless of approvals. Turn this on if you want to run the app in monitor-only mode.</div>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" id="f_kill_switch" onchange="updateKillSwitch()"/>
            <span class="toggle-track"></span>
          </label>
        </div>
      </div>
      <div class="field-grid">
        <div class="field">
          <label class="field-label">Max Daily Loss</label>
          <div class="field-row">
            <span class="field-prefix">$</span>
            <input type="number" id="f_max_daily_loss" class="finput" style="width:110px;" min="0" step="50" placeholder="No limit"/>
          </div>
          <div class="field-hint">If the portfolio loses more than this in one day, no further orders are sent. Leave blank for no limit.</div>
        </div>
        <div class="field">
          <label class="field-label">Max Single Order Size</label>
          <div class="field-row">
            <span class="field-prefix">$</span>
            <input type="number" id="f_max_order_size" class="finput" style="width:110px;" min="0" step="100" placeholder="No limit"/>
          </div>
          <div class="field-hint">Hard cap on the notional value of any single order. Rejects orders above this even if approved. Leave blank for no limit.</div>
        </div>
        <div class="field">
          <label class="field-label">Max Open Positions</label>
          <div class="field-row">
            <input type="number" id="f_max_positions" class="finput finput-num" min="1" step="1" placeholder="No limit"/>
            <span class="field-unit">positions</span>
          </div>
          <div class="field-hint">Block new entries when this many positions are already open. Leave blank for no limit.</div>
        </div>
        <div class="field">
          <label class="field-label">Max Single Trade Risk</label>
          <div class="field-row">
            <span class="field-prefix">$</span>
            <input type="number" id="f_max_trade_risk" class="finput" style="width:110px;" min="0" step="50" placeholder="No limit"/>
          </div>
          <div class="field-hint">Maximum dollars at risk (cost basis) per individual trade. Leave blank for no limit.</div>
        </div>
        <div class="field">
          <label class="field-label">Max Symbol Allocation</label>
          <div class="field-row">
            <input type="number" id="f_max_symbol_pct" class="finput finput-num" min="0" max="100" step="1" placeholder="No limit"/>
            <span class="field-unit">% of portfolio</span>
          </div>
          <div class="field-hint">Reject orders that would put more than this percentage of your portfolio in one symbol. Leave blank for no limit.</div>
        </div>
      </div>
      <div class="field-grid col1" style="margin-top:12px;">
        <div class="toggle-field" id="requireStopRow">
          <div class="toggle-text">
            <div class="toggle-label">Require Stop-Loss on Entries</div>
            <div class="toggle-desc">When ON, entry orders without an attached stop-loss order are blocked. Enforces disciplined risk management on every new position.</div>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" id="f_require_stop"/>
            <span class="toggle-track"></span>
          </label>
        </div>
        <div class="toggle-field" id="regimeRow">
          <div class="toggle-text">
            <div class="toggle-label">Regime Gate</div>
            <div class="toggle-desc">When ON, the AI checks the macro market regime (bull/bear/neutral) before placing entries. Reduces exposure during high-risk macro environments.</div>
          </div>
          <label class="toggle-switch green">
            <input type="checkbox" id="f_regime" checked/>
            <span class="toggle-track"></span>
          </label>
        </div>
      </div>
    </div>

  </div><!-- /.settings-body -->
</div><!-- /.settings-shell -->

<div class="save-bar">
  <button type="button" class="btn-save" id="saveBtn" onclick="saveAll()">Save Changes</button>
  <span class="save-msg" id="saveMsg">Changes saved</span>
  <span class="save-err" id="saveErr">Save failed — check console</span>
</div>

<script>
  // Nav click: prevent default anchor jump, scroll section into view manually
  function navClick(e, el) {
    e.preventDefault();
    document.querySelectorAll('.snav-item').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
    const target = document.getElementById(el.getAttribute('href').slice(1));
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // Scroll-spy via IntersectionObserver on each section
  const _sectionIds = ['connections','notifications','risk-scan','opp-scan','guardrails'];
  const _observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        document.querySelectorAll('.snav-item').forEach(n => {
          n.classList.toggle('active', n.getAttribute('href') === '#' + entry.target.id);
        });
      }
    });
  }, { rootMargin: '-20% 0px -70% 0px', threshold: 0 });
  _sectionIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) _observer.observe(el);
  });

  function updateKillSwitch() {
    const on = document.getElementById('f_kill_switch').checked;
    document.getElementById('killSwitchRow').classList.toggle('on', on);
  }

  // ── Watchlist chip UI ────────────────────────────────────────────────────
  function wlTickers() {
    const v = document.getElementById('f_watchlist').value;
    return v ? v.split(',').map(s => s.trim().toUpperCase()).filter(Boolean) : [];
  }
  function wlSync(tickers) {
    document.getElementById('f_watchlist').value = tickers.join(',');
    const box = document.getElementById('watchlist-chips');
    box.innerHTML = '';
    tickers.forEach(function(t) {
      const chip = document.createElement('span');
      chip.style.cssText = 'display:inline-flex;align-items:center;gap:4px;padding:3px 8px 3px 10px;background:rgba(37,99,235,.15);color:#93c5fd;border:1px solid rgba(37,99,235,.25);border-radius:20px;font-size:12px;font-weight:600;letter-spacing:.04em;cursor:default;';
      chip.innerHTML = t + '<button type="button" style="background:none;border:none;color:#93c5fd;opacity:.6;cursor:pointer;padding:0 0 0 2px;font-size:13px;line-height:1;" onclick="wlRemove(\'' + t + '\')">&times;</button>';
      box.appendChild(chip);
    });
  }
  function wlAddTicker(raw) {
    const t = raw.trim().toUpperCase().replace(/[^A-Z0-9.]/g, '');
    if (!t) return;
    const list = wlTickers();
    if (!list.includes(t)) { list.push(t); wlSync(list); }
  }
  function wlRemove(t) {
    wlSync(wlTickers().filter(function(x){ return x !== t; }));
  }
  function wlSet(csv) {
    wlSync(csv ? csv.split(',').map(s => s.trim().toUpperCase()).filter(Boolean) : []);
  }

  async function loadSettings() {
    try {
      const r = await fetch('/api/v1/settings');
      if (!r.ok) return;
      const d = await r.json();
      // Connections — secrets never sent back; show configured status only
      if (d.schwab_configured) {
        document.getElementById('f_schwab_key').placeholder    = 'Configured (leave blank to keep)';
        document.getElementById('f_schwab_secret').placeholder = 'Configured (leave blank to keep)';
      }
      if (d.schwab_callback_url) document.getElementById('f_schwab_callback').value = d.schwab_callback_url;
      if (d.anthropic_configured) document.getElementById('f_anthropic_key').placeholder = 'Configured (leave blank to keep)';
      if (d.quiver_quant_configured) document.getElementById('f_quiver_key').placeholder = 'Configured (leave blank to keep)';
      if (d.fred_configured) document.getElementById('f_fred_key').placeholder = 'Configured (leave blank to keep)';
      if (d.twilio_configured) {
        document.getElementById('f_twilio_sid').placeholder   = 'Configured (leave blank to keep)';
        document.getElementById('f_twilio_token').placeholder = 'Configured (leave blank to keep)';
      }
      if (d.twilio_from_number) document.getElementById('f_twilio_from').value = d.twilio_from_number;
      // Notifications
      document.getElementById('f_phone').value         = d.alert_phone_number ?? '';
      document.getElementById('f_dashboard_url').value = d.dashboard_url ?? '';
      document.getElementById('f_alert_email').value   = d.alert_email_address ?? '';
      document.getElementById('f_smtp_host').value     = d.email_smtp_host ?? '';
      document.getElementById('f_smtp_port').value     = d.email_smtp_port ?? 587;
      document.getElementById('f_smtp_user').value     = d.email_smtp_user ?? '';
      // Risk scan
      document.getElementById('f_gain_pct').value        = d.alert_gain_pct ?? 30;
      document.getElementById('f_down_pct').value        = d.alert_position_down_pct ?? 8;
      document.getElementById('f_day_loss').value        = d.alert_day_loss_pct ?? 5;
      document.getElementById('f_concentration').value   = d.alert_concentration_pct ?? 25;
      document.getElementById('f_earnings_days').value   = d.alert_earnings_days ?? 3;
      document.getElementById('f_interval').value        = d.agent_check_interval_minutes ?? 30;
      // Opportunity scan
      document.getElementById('f_buy_budget').value        = d.buy_scan_budget ?? 2000;
      document.getElementById('f_buy_interval').value      = d.buy_scan_interval_hours ?? 24;
      document.getElementById('f_buy_max').value           = d.buy_scan_max_proposals ?? 3;
      wlSet(d.buy_scan_watchlist ?? '');
      document.getElementById('f_email_min_upside').value  = d.email_min_upside_pct ?? 15;
      // Safety guardrails
      const ks = d.live_order_kill_switch === true || d.live_order_kill_switch === 'true';
      document.getElementById('f_kill_switch').checked = ks;
      updateKillSwitch();
      const numOrEmpty = v => v != null ? v : '';
      document.getElementById('f_max_daily_loss').value  = numOrEmpty(d.live_order_max_daily_loss_dollars);
      document.getElementById('f_max_order_size').value  = numOrEmpty(d.live_order_max_order_notional_dollars);
      document.getElementById('f_max_positions').value   = numOrEmpty(d.live_order_max_open_positions);
      document.getElementById('f_max_trade_risk').value  = numOrEmpty(d.live_order_max_single_trade_risk_dollars);
      document.getElementById('f_max_symbol_pct').value  = numOrEmpty(d.live_order_max_symbol_allocation_pct);
      document.getElementById('f_require_stop').checked  = d.live_order_require_stop_loss_for_entries === true || d.live_order_require_stop_loss_for_entries === 'true';
      document.getElementById('f_regime').checked        = d.regime_enabled !== false && d.regime_enabled !== 'false';
    } catch(e) { console.error('loadSettings:', e); }
  }

  async function saveAll() {
    const btn = document.getElementById('saveBtn');
    btn.disabled = true; btn.textContent = 'Saving\u2026';
    const msgEl = document.getElementById('saveMsg');
    const errEl = document.getElementById('saveErr');
    msgEl.style.opacity = '0'; errEl.style.opacity = '0';

    const numOrNull = id => {
      const v = document.getElementById(id).value.trim();
      return v === '' ? null : +v;
    };
    const strOrSkip = id => {
      const v = document.getElementById(id).value.trim();
      return v || null;
    };

    try {
      const payload = {
        // Notifications
        alert_phone_number:   document.getElementById('f_phone').value.trim(),
        dashboard_url:        document.getElementById('f_dashboard_url').value.trim(),
        alert_email_address:  document.getElementById('f_alert_email').value.trim(),
        email_smtp_host:      document.getElementById('f_smtp_host').value.trim(),
        email_smtp_port:      +document.getElementById('f_smtp_port').value || 587,
        email_smtp_user:      document.getElementById('f_smtp_user').value.trim(),
        // Risk scan
        alert_gain_pct:               +document.getElementById('f_gain_pct').value,
        alert_position_down_pct:      +document.getElementById('f_down_pct').value,
        alert_day_loss_pct:           +document.getElementById('f_day_loss').value,
        alert_concentration_pct:      +document.getElementById('f_concentration').value,
        alert_earnings_days:          +document.getElementById('f_earnings_days').value,
        agent_check_interval_minutes: +document.getElementById('f_interval').value,
        // Opportunity scan
        buy_scan_budget:         +document.getElementById('f_buy_budget').value,
        buy_scan_interval_hours: +document.getElementById('f_buy_interval').value,
        buy_scan_max_proposals:  +document.getElementById('f_buy_max').value,
        buy_scan_watchlist:      document.getElementById('f_watchlist').value.trim(),
        email_min_upside_pct:    +document.getElementById('f_email_min_upside').value,
        // Safety guardrails
        live_order_kill_switch:                       document.getElementById('f_kill_switch').checked,
        live_order_max_daily_loss_dollars:            numOrNull('f_max_daily_loss'),
        live_order_max_order_notional_dollars:        numOrNull('f_max_order_size'),
        live_order_max_open_positions:                numOrNull('f_max_positions'),
        live_order_max_single_trade_risk_dollars:     numOrNull('f_max_trade_risk'),
        live_order_max_symbol_allocation_pct:         numOrNull('f_max_symbol_pct'),
        live_order_require_stop_loss_for_entries:     document.getElementById('f_require_stop').checked,
        regime_enabled:                               document.getElementById('f_regime').checked,
      };
      // Connection secrets: only include if user typed something (blank = keep existing)
      const schwabKey    = strOrSkip('f_schwab_key');
      const schwabSecret = strOrSkip('f_schwab_secret');
      const callbackUrl  = document.getElementById('f_schwab_callback').value.trim();
      const anthropicKey = strOrSkip('f_anthropic_key');
      const quiverKey    = strOrSkip('f_quiver_key');
      const fredKey      = strOrSkip('f_fred_key');
      const twilioSid    = strOrSkip('f_twilio_sid');
      const twilioToken  = strOrSkip('f_twilio_token');
      const twilioFrom   = document.getElementById('f_twilio_from').value.trim();
      const smtpPass     = document.getElementById('f_smtp_pass').value;
      if (schwabKey)    payload.schwab_app_key       = schwabKey;
      if (schwabSecret) payload.schwab_app_secret    = schwabSecret;
      if (callbackUrl)  payload.schwab_callback_url  = callbackUrl;
      if (anthropicKey) payload.anthropic_api_key    = anthropicKey;
      if (quiverKey)    payload.quiver_quant_api_key = quiverKey;
      if (fredKey)      payload.fred_api_key         = fredKey;
      if (twilioSid)    payload.twilio_account_sid   = twilioSid;
      if (twilioToken)  payload.twilio_auth_token    = twilioToken;
      if (twilioFrom)   payload.twilio_from_number   = twilioFrom;
      if (smtpPass)     payload.email_smtp_password  = smtpPass;

      const res = await fetch('/api/v1/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      msgEl.style.opacity = '1';
      setTimeout(() => { msgEl.style.opacity = '0'; }, 3000);
    } catch(e) {
      console.error(e);
      errEl.style.opacity = '1';
      setTimeout(() => { errEl.style.opacity = '0'; }, 4000);
    } finally {
      btn.disabled = false; btn.textContent = 'Save Changes';
    }
  }

  loadSettings();
</script>
</body>
</html>"""


def _home_html() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Schwab API Trader · Setup</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%231e3a5f'/%3E%3Cpolyline points='4,22 10,16 16,19 22,10 28,6' fill='none' stroke='%2322c55e' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg: #f5f4f0;
      --card: #ffffff;
      --ink: #1a1a1a;
      --muted: #6b7280;
      --line: #e5e7eb;
      --green: #059669;
      --green-bg: #ecfdf5;
      --green-ring: #6ee7b7;
      --amber: #d97706;
      --amber-bg: #fffbeb;
      --red: #dc2626;
      --red-bg: #fef2f2;
      --blue: #2563eb;
      --accent: #0f766e;
      --accent-dark: #115e59;
    }

    body {
      min-height: 100vh;
      background: var(--bg);
      font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      color: var(--ink);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: flex-start;
      padding: 48px 20px 80px;
    }

    /* ── logo / wordmark ── */
    .wordmark {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--accent);
      margin-bottom: 40px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .wordmark svg { width: 22px; height: 22px; }

    /* ── card ── */
    .card {
      width: 100%;
      max-width: 440px;
      background: var(--card);
      border-radius: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,.07), 0 8px 32px rgba(0,0,0,.06);
      padding: 40px 36px;
    }

    /* ── states (shown/hidden via JS) ── */
    .state { display: none; flex-direction: column; gap: 24px; }
    .state.active { display: flex; }

    /* ── status badge ── */
    .badge {
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 12px; font-weight: 600; letter-spacing: .03em;
      text-transform: uppercase; border-radius: 999px;
      padding: 5px 12px; width: fit-content;
    }
    .badge-green  { background: var(--green-bg);  color: var(--green);  }
    .badge-amber  { background: var(--amber-bg);  color: var(--amber);  }
    .badge-red    { background: var(--red-bg);     color: var(--red);    }

    .badge .dot {
      width: 6px; height: 6px; border-radius: 50%;
      background: currentColor;
    }
    .badge-green .dot { animation: pulse 2s infinite; }
    @keyframes pulse {
      0%,100% { opacity: 1; } 50% { opacity: .4; }
    }

    /* ── headings ── */
    h1 { font-size: 26px; font-weight: 700; letter-spacing: -.03em; line-height: 1.2; }
    .sub { font-size: 15px; color: var(--muted); line-height: 1.55; }

    /* ── primary CTA ── */
    .btn-primary {
      display: flex; align-items: center; justify-content: center; gap: 10px;
      width: 100%; padding: 16px 24px;
      background: var(--accent); color: #fff;
      font-size: 16px; font-weight: 700; letter-spacing: -.01em;
      border: none; border-radius: 14px; cursor: pointer;
      transition: background .15s, transform .1s, box-shadow .15s;
      text-decoration: none;
      box-shadow: 0 2px 8px rgba(15,118,110,.25);
    }
    .btn-primary:hover { background: var(--accent-dark); box-shadow: 0 4px 16px rgba(15,118,110,.35); }
    .btn-primary:active { transform: scale(.98); }
    .btn-primary:disabled { opacity: .5; cursor: not-allowed; transform: none; }
    .btn-primary svg { width: 18px; height: 18px; flex-shrink: 0; }

    /* ── secondary / ghost ── */
    .btn-ghost {
      display: flex; align-items: center; justify-content: center; gap: 8px;
      width: 100%; padding: 13px 20px;
      background: transparent; color: var(--muted);
      font-size: 14px; font-weight: 500;
      border: 1.5px solid var(--line); border-radius: 12px; cursor: pointer;
      transition: border-color .15s, color .15s;
      text-decoration: none;
    }
    .btn-ghost:hover { border-color: #9ca3af; color: var(--ink); }

    /* ── divider ── */
    .divider {
      display: flex; align-items: center; gap: 10px;
      font-size: 12px; color: var(--muted);
    }
    .divider::before, .divider::after {
      content: ''; flex: 1; height: 1px; background: var(--line);
    }

    /* ── code paste input ── */
    .input-wrap { position: relative; }
    .input-wrap input {
      width: 100%; padding: 14px 48px 14px 16px;
      border: 1.5px solid var(--line); border-radius: 12px;
      font: inherit; font-size: 14px; background: #fff;
      transition: border-color .15s, box-shadow .15s;
      outline: none;
    }
    .input-wrap input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(15,118,110,.12); }
    .input-wrap input::placeholder { color: #9ca3af; }
    .paste-btn {
      position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
      background: var(--bg); border: 1px solid var(--line); border-radius: 7px;
      padding: 4px 8px; font-size: 11px; font-weight: 600; color: var(--muted);
      cursor: pointer;
    }
    .paste-btn:hover { background: #e5e7eb; }

    /* ── instruction steps ── */
    .steps { display: flex; flex-direction: column; gap: 14px; }
    .step { display: flex; gap: 14px; align-items: flex-start; }
    .step-num {
      width: 26px; height: 26px; border-radius: 50%;
      background: var(--accent); color: #fff;
      font-size: 12px; font-weight: 700;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0; margin-top: 1px;
    }
    .step-text { font-size: 14px; color: var(--ink); line-height: 1.5; }
    .step-text b { font-weight: 600; }

    /* ── success check ── */
    .check-icon {
      width: 64px; height: 64px; border-radius: 50%;
      background: var(--green-bg);
      display: flex; align-items: center; justify-content: center;
      margin: 0 auto;
    }
    .check-icon svg { width: 32px; height: 32px; color: var(--green); }

    .text-center { text-align: center; }

    /* ── countdown ring ── */
    .countdown { font-size: 13px; color: var(--muted); text-align: center; }
    .countdown b { color: var(--ink); }

    /* ── notice box ── */
    .notice {
      background: var(--amber-bg); border: 1px solid #fde68a;
      border-radius: 12px; padding: 14px 16px;
      font-size: 13px; color: #78350f; line-height: 1.5;
    }
    .notice b { font-weight: 600; }

    /* ── error ── */
    .error-msg {
      background: var(--red-bg); border: 1px solid #fecaca;
      border-radius: 12px; padding: 14px 16px;
      font-size: 13px; color: var(--red); line-height: 1.5;
      display: none;
    }

    /* ── spinner ── */
    @keyframes spin { to { transform: rotate(360deg); } }
    .spinner {
      width: 18px; height: 18px; border-radius: 50%;
      border: 2px solid rgba(255,255,255,.4);
      border-top-color: #fff;
      animation: spin .7s linear infinite;
      flex-shrink: 0;
    }

    /* ── misconfig state ── */
    .config-list {
      font-size: 13px; line-height: 1.7; color: var(--muted);
      padding-left: 18px;
    }
    .config-list li { color: var(--ink); }
    code {
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 12px; background: #f3f4f6;
      padding: 1px 5px; border-radius: 4px;
    }

    @media (max-width: 480px) {
      body { padding: 32px 16px 60px; }
      .card { padding: 28px 22px; }
    }
  </style>
</head>
<body>

<div class="wordmark">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
       stroke-linecap="round" stroke-linejoin="round">
    <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
    <polyline points="16 7 22 7 22 13"/>
  </svg>
  Schwab API Trader
</div>

<div class="card">

  <!-- ── STATE: loading ── -->
  <div class="state active" id="stateLoading">
    <div style="text-align:center;padding:20px 0;color:var(--muted);font-size:14px;">
      Checking your connection&hellip;
    </div>
  </div>

  <!-- ── STATE: misconfigured (.env not set up) ── -->
  <div class="state" id="stateMisconfig">
    <div class="badge badge-red"><div class="dot"></div> Not configured</div>
    <div>
      <h1>App needs setup</h1>
      <p class="sub" style="margin-top:8px;">A few environment variables are missing from your <code>.env</code> file before you can connect.</p>
    </div>
    <div class="notice">
      <b>Add these to your <code>.env</code> file, then restart the server:</b>
      <ul id="missingList" class="config-list" style="margin-top:8px;"></ul>
    </div>
    <button class="btn-ghost" onclick="checkStatus()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4"/></svg>
      Check again after restarting
    </button>
  </div>

  <!-- ── STATE: needs login ── -->
  <div class="state" id="stateLogin">
    <div class="badge badge-amber"><div class="dot"></div> Not connected</div>
    <div>
      <h1>Connect your Schwab account</h1>
      <p class="sub" style="margin-top:8px;">Sign in once and your portfolio loads automatically every time.</p>
    </div>
    <a class="btn-primary" href="/auth/start" id="schwabLoginBtn">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14L21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>
      Sign in with Schwab
    </a>

    <div class="divider">if Schwab redirects you back here with a code</div>

    <div>
      <p class="sub" style="font-size:13px;margin-bottom:10px;">
        Paste the code from the URL Schwab sent you to (look for <code>code=…</code> in the address bar).
      </p>
      <form id="codeForm" style="display:flex;flex-direction:column;gap:10px;">
        <div class="input-wrap">
          <input id="codeInput" placeholder="Paste authorization code here" autocomplete="off" spellcheck="false"/>
          <button type="button" class="paste-btn" id="pasteBtn">Paste</button>
        </div>
        <button type="submit" class="btn-primary" id="codeSubmitBtn">
          <span id="codeSubmitLabel">Connect</span>
        </button>
      </form>
      <div class="error-msg" id="codeError"></div>
    </div>
  </div>

  <!-- ── STATE: connected ── -->
  <div class="state" id="stateConnected">
    <div class="check-icon">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
           stroke-linecap="round" stroke-linejoin="round">
        <polyline points="20 6 9 17 4 12"/>
      </svg>
    </div>
    <div class="text-center">
      <h1>You&rsquo;re connected!</h1>
      <p class="sub" style="margin-top:8px;">Your Schwab account is linked and ready.</p>
    </div>
    <a class="btn-primary" href="/dashboard" id="dashboardBtn">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
      Go to Dashboard
    </a>
    <div class="countdown" id="countdown">Taking you there in <b id="countNum">5</b>s &nbsp;&middot;&nbsp;
      <a href="#" onclick="cancelRedirect();return false;" style="color:var(--muted);">Stay here</a>
    </div>
    <button class="btn-ghost" onclick="reconnect()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4"/></svg>
      Reconnect Schwab (re-auth)
    </button>
  </div>

</div><!-- /.card -->

<script>
  const $ = id => document.getElementById(id);
  let _redirectTimer = null;
  let _redirectCancelled = false;

  function show(stateId) {
    document.querySelectorAll('.state').forEach(s => s.classList.remove('active'));
    $(stateId).classList.add('active');
  }

  async function checkStatus() {
    show('stateLoading');
    try {
      const r = await fetch('/api/v1/app/status');
      const d = await r.json();

      if (!d.oauth_settings_complete) {
        const list = $('missingList');
        list.innerHTML = d.missing_settings.map(s => '<li><code>' + s + '</code></li>').join('');
        show('stateMisconfig');
        return;
      }

      if (d.authenticated) {
        show('stateConnected');
        if (!_redirectCancelled) startCountdown();
      } else {
        show('stateLogin');
      }
    } catch(e) {
      show('stateLogin'); // best-effort fallback
    }
  }

  // ── Auto-redirect countdown ─────────────────────────────────
  function startCountdown() {
    let n = 5;
    $('countNum').textContent = n;
    _redirectTimer = setInterval(() => {
      n--;
      $('countNum').textContent = n;
      if (n <= 0) {
        clearInterval(_redirectTimer);
        if (!_redirectCancelled) window.location.href = '/dashboard';
      }
    }, 1000);
  }

  function cancelRedirect() {
    _redirectCancelled = true;
    clearInterval(_redirectTimer);
    $('countdown').textContent = 'Staying here.';
  }

  function reconnect() {
    cancelRedirect();
    show('stateLogin');
  }

  // ── Paste button ────────────────────────────────────────────
  $('pasteBtn').addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      // Extract just the code value if user pasted a full URL
      const match = text.match(/[?&]code=([^& ]+)/);
      $('codeInput').value = match ? decodeURIComponent(match[1]) : text.trim();
      $('codeInput').focus();
    } catch {
      $('codeInput').focus();
    }
  });

  // ── Code exchange form ──────────────────────────────────────
  $('codeForm').addEventListener('submit', async e => {
    e.preventDefault();
    const code = $('codeInput').value.trim();
    if (!code) { showError('Please paste the code from Schwab first.'); return; }

    $('codeSubmitBtn').disabled = true;
    $('codeSubmitLabel').innerHTML = '<span class="spinner"></span> Connecting\u2026';

    try {
      const r = await fetch('/api/v1/auth/exchange-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, session: null }),
      });
      const d = await r.json();
      if (!r.ok) {
        showError(d.detail || 'Connection failed. Check your code and try again.');
        $('codeSubmitBtn').disabled = false;
        $('codeSubmitLabel').textContent = 'Connect';
        return;
      }
      // Success
      $('codeError').style.display = 'none';
      show('stateConnected');
      startCountdown();
    } catch {
      showError('Something went wrong. Please try again.');
      $('codeSubmitBtn').disabled = false;
      $('codeSubmitLabel').textContent = 'Connect';
    }
  });

  function showError(msg) {
    const el = $('codeError');
    el.textContent = msg;
    el.style.display = 'block';
  }

  // ── Boot ────────────────────────────────────────────────────
  checkStatus();
</script>
</body>
</html>
"""


def _live_dashboard_html() -> str:
    return _DASHBOARD_HTML_TEMPLATE


_DASHBOARD_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Trading Dashboard — Schwab API Trader</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%231e3a5f'/%3E%3Cpolyline points='4,22 10,16 16,19 22,10 28,6' fill='none' stroke='%2322c55e' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <script src="https://unpkg.com/lucide@0.447.0/dist/umd/lucide.min.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg:       #080B10;
      --surface:  #0E1318;
      --surface2: #141A22;
      --surface3: #1C242E;
      --ink:      #E8EDF5;
      --muted:    #7A8599;
      --dim:      #444D5E;
      --line:     rgba(240,246,252,0.07);
      --line2:    rgba(240,246,252,0.12);
      --accent:   #2563EB;
      --accent-soft: rgba(37,99,235,0.10);
      --green:    #22C55E;
      --green-soft: rgba(34,197,94,0.10);
      --red:      #EF4444;
      --red-soft: rgba(239,68,68,0.10);
      --amber:    #F59E0B;
      --radius:   8px;
      --radius-lg: 12px;
      --shadow:   0 4px 24px rgba(0,0,0,0.4);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--ink);
      font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      font-size: 14px;
      -webkit-font-smoothing: antialiased;
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum";
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 24px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .brand { font-weight: 700; font-size: 15px; letter-spacing: -0.02em; color: var(--ink); text-decoration: none; }
    .nav { display: flex; align-items: center; gap: 10px; }
    .nav a { color: var(--muted); text-decoration: none; font-size: 13px; padding: 5px 10px; border-radius: 6px; transition: color .15s, background .15s; }
    .nav a:hover { color: var(--ink); background: var(--surface2); }
    .market-pill {
      display: flex; align-items: center; gap: 6px;
      background: var(--surface2); border: 1px solid var(--line);
      border-radius: 99px; padding: 4px 10px; font-size: 12px; color: var(--muted);
    }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); flex-shrink: 0; }
    .dot.open { background: var(--green); }
    .dot.closed { background: var(--red); }
    main { max-width: 1440px; margin: 0 auto; padding: 20px 20px 48px; }
    /* ── Health Score card ── */
    .health-card { background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px 18px;display:flex;flex-direction:column;justify-content:space-between; }
    .health-ring-wrap { display:flex;align-items:center;gap:12px;margin-top:6px; }
    .health-ring { flex-shrink:0; }
    .health-score-num { font-size:26px;font-weight:700;letter-spacing:-0.04em;line-height:1.1; }
    .health-label { font-size:11px;color:var(--muted);margin-top:2px; }
    /* ── Briefing card ── */
    .briefing-card { background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:0;overflow:hidden;margin-bottom:14px; }
    .briefing-header { display:flex;align-items:center;justify-content:space-between;padding:12px 16px 10px;border-bottom:1px solid var(--line); }
    .briefing-title { font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--green); }
    .briefing-age { font-size:11px;color:var(--muted); }
    .briefing-headline { font-size:14px;font-weight:600;line-height:1.45;padding:12px 16px 8px;color:var(--ink); }
    .briefing-bullets { padding:0 16px 10px;display:flex;flex-direction:column;gap:4px; }
    .briefing-bullet { display:flex;gap:8px;font-size:12px;color:var(--muted);line-height:1.5; }
    .briefing-bullet::before { content:'–';color:var(--green);flex-shrink:0;margin-top:1px; }
    .briefing-footer { display:flex;align-items:center;justify-content:space-between;padding:8px 16px 12px;border-top:1px solid var(--line); }
    .briefing-action { font-size:12px;font-weight:600;color:var(--ink); }
    .briefing-watch { font-size:11px;color:var(--muted); }
    /* ── Exit target progress ── */
    .exit-target-bar { margin:8px 14px 0;background:rgba(255,255,255,0.04);border-radius:8px;padding:8px 12px;border:1px solid var(--line); }
    .exit-target-label { display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin-bottom:5px;text-transform:uppercase;letter-spacing:.05em; }
    .exit-track { position:relative;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:visible; }
    .exit-fill { height:100%;border-radius:3px;transition:width .5s; }
    .exit-cursor { position:absolute;top:-3px;width:12px;height:12px;border-radius:50%;border:2px solid var(--surface);transform:translateX(-50%); }
    /* ── Mute button on flag items ── */
    .btn-mute { background:none;border:1px solid var(--line);color:var(--muted);border-radius:5px;padding:2px 7px;font-size:10px;cursor:pointer;font-family:inherit;transition:all .15s;flex-shrink:0; }
    .btn-mute:hover { border-color:#fbbf24;color:#fbbf24; }
    /* ── AI Quick Take in drill panel ── */
    .quick-take-wrap { padding:12px 18px;border-top:1px solid var(--line); }
    .quick-take-header { display:flex;align-items:center;justify-content:space-between;margin-bottom:8px; }
    .quick-take-label { font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--green); }
    .quick-take-signal { font-size:10px;font-weight:700;letter-spacing:.06em;border-radius:5px;padding:2px 8px; }
    .quick-take-text { font-size:12px;color:var(--muted);line-height:1.6; }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 12px;
      margin-bottom: 20px;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 18px 20px;
      cursor: pointer;
      transition: border-color .15s, box-shadow .15s;
    }
    .card:hover { border-color: rgba(255,255,255,.2); box-shadow: 0 4px 20px rgba(0,0,0,.35); }
    .card-label { font-size: 10px; text-transform: uppercase; letter-spacing: .09em; color: var(--dim); margin-bottom: 6px; font-weight: 600; }
    .card-value { font-size: 26px; font-weight: 700; letter-spacing: -0.04em; line-height: 1.1; }
    .card-sub { font-size: 11.5px; color: var(--muted); margin-top: 5px; }
    /* ── Stat drill-down modal ── */
    .stat-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); backdrop-filter:blur(4px); z-index:900; align-items:center; justify-content:center; }
    .stat-overlay.open { display:flex; }
    .stat-box { background:var(--surface); border:1px solid var(--line); border-radius:16px; width:min(480px,92vw); max-height:80vh; display:flex; flex-direction:column; overflow:hidden; }
    .stat-box-head { display:flex; align-items:center; justify-content:space-between; padding:16px 20px; border-bottom:1px solid var(--line); }
    .stat-box-title { font-size:13px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; color:var(--dim); }
    .stat-box-close { background:none; border:none; color:var(--muted); font-size:20px; cursor:pointer; line-height:1; padding:0 4px; }
    .stat-box-close:hover { color:var(--ink); }
    .stat-box-body { overflow-y:auto; padding:14px 20px 20px; }
    .stat-row { display:flex; justify-content:space-between; align-items:center; padding:9px 0; border-bottom:1px solid rgba(255,255,255,.04); font-size:13px; }
    .stat-row:last-child { border-bottom:none; }
    .stat-row-sym { font-weight:700; color:var(--ink); min-width:60px; }
    .stat-row-name { color:var(--muted); font-size:11px; flex:1; padding:0 10px; }
    .stat-row-val { font-weight:600; text-align:right; }
    .stat-section { font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); font-weight:700; margin:14px 0 6px; }
    .stat-big { font-size:22px; font-weight:700; letter-spacing:-.03em; margin:4px 0 2px; }
    .stat-sub { font-size:11px; color:var(--muted); }
    .gain { color: var(--green); }
    .loss { color: var(--red); }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      overflow: hidden;
      position: relative;
    }
    .panel-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 16px 20px; min-height: 52px;
      border-bottom: 1px solid var(--line);
    }
    .panel-title { font-size: 13px; font-weight: 600; letter-spacing: -.01em; }
    .panel-meta { display: flex; align-items: center; gap: 8px; }
    .last-updated { font-size: 11px; color: var(--dim); }
    .btn {
      background: none; border: 1px solid var(--line); color: var(--muted);
      padding: 5px 11px; border-radius: 6px; font-size: 12px; cursor: pointer;
      transition: all .15s; font-family: inherit; font-weight: 500;
    }
    .btn:hover { border-color: var(--line2); color: var(--ink); background: var(--surface2); }
    .btn:disabled { opacity: .4; cursor: not-allowed; }
    table { width: 100%; border-collapse: collapse; }
    thead th {
      padding: 9px 14px; text-align: right;
      font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
      color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--line);
      cursor: pointer; user-select: none; white-space: nowrap;
      position: sticky; top: 0; z-index: 2; background: var(--surface);
    }
    thead th:first-child { text-align: left; }
    thead th:hover { color: var(--ink); }
    thead th.sort-asc::after { content: ' ↑'; color: var(--accent); }
    thead th.sort-desc::after { content: ' ↓'; color: var(--accent); }
    tbody tr { border-bottom: 1px solid var(--line); transition: background .1s; }
    tbody tr:last-child { border-bottom: none; }
    tbody tr:hover { background: var(--surface2); }
    tbody td { padding: 11px 14px; text-align: right; font-size: 13px; }
    tbody td:first-child { text-align: left; }
    .sym { font-weight: 700; font-size: 14px; letter-spacing: -.01em; }
    .sub-text { font-size: 11px; color: var(--muted); margin-top: 2px; }
    .bar-wrap { display: flex; align-items: center; gap: 8px; justify-content: flex-end; }
    .mini-bar { height: 4px; border-radius: 2px; min-width: 4px; max-width: 80px; }
    .bar-pos { background: var(--green); }
    .bar-neg { background: var(--red); }
    .error-box {
      background: var(--red-soft); border: 1px solid rgba(248,81,73,.3);
      color: #fca5a5; border-radius: 10px; padding: 12px 16px;
      font-size: 13px; margin-bottom: 16px; display: none;
    }
    .empty-row td { text-align: center !important; padding: 40px; color: var(--muted); }
    .skel { background: linear-gradient(90deg, var(--surface) 25%, var(--surface2) 50%, var(--surface) 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 4px; display: inline-block; }
    @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
    @keyframes flash-up   { 0%,100%{background:transparent} 50%{background:rgba(63,185,80,0.35)} }
    @keyframes flash-down { 0%,100%{background:transparent} 50%{background:rgba(248,81,73,0.35)} }
    .flash-up   { animation: flash-up   0.7s ease; }
    .flash-down { animation: flash-down 0.7s ease; }
    .period-btn { background:var(--surface2);border:1px solid var(--line);border-radius:6px;color:var(--muted);padding:3px 10px;font-size:12px;cursor:pointer;transition:all .15s; }
    .period-btn:hover { color:var(--ink); }
    .period-active { background:var(--accent)!important;border-color:var(--accent)!important;color:#fff!important;font-weight:600; }
    .perf-stat-grid { display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px; }
    .perf-stat { background:var(--surface2);border-radius:8px;padding:10px 12px; }
    .perf-stat-label { font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px; }
    .perf-stat-val { font-size:18px;font-weight:700;letter-spacing:-0.03em; }
    @media (max-width: 1100px) {
      .summary-grid { grid-template-columns: repeat(3, 1fr); }
    }
    @media (max-width: 900px) {
      .summary-grid { grid-template-columns: repeat(2, 1fr); }
      .hide-sm { display: none; }
    }
    @media (max-width: 600px) {
      .summary-grid { grid-template-columns: 1fr 1fr; }
      main { padding: 12px 12px 32px; }
    }
    /* Earnings */
    .earn-row { display:flex; align-items:center; gap:12px; padding:10px 18px; border-bottom:1px solid var(--line); font-size:13px; }
    .earn-row:last-child { border-bottom:none; }
    .earn-sym { font-weight:700; width:56px; flex-shrink:0; }
    .earn-date { color:var(--muted); width:100px; flex-shrink:0; }
    .earn-badge { border-radius:99px; padding:2px 9px; font-size:11px; font-weight:600; flex-shrink:0; }
    .badge-urgent { background:rgba(248,81,73,.15); color:var(--red); }
    .badge-soon   { background:rgba(251,191,36,.12); color:#fbbf24; }
    .badge-normal { background:var(--surface2); color:var(--muted); }
    .brief-btn { margin-left:auto; background:none; border:1px solid var(--line); color:var(--muted); padding:4px 10px; border-radius:6px; font-size:11px; cursor:pointer; font-family:inherit; white-space:nowrap; }
    .brief-btn:hover { border-color:var(--accent); color:var(--ink); }

    /* ── Alert cards ──────────────────────────────────────── */
    .alert-card { padding:16px 18px; border-bottom:1px solid var(--line); transition:opacity .2s; }
    .alert-card:last-child { border-bottom:none; }
    .alert-card.is-dismissed { opacity:.35; pointer-events:none; }
    .alert-card-header { display:flex; align-items:center; gap:8px; margin-bottom:10px; }
    .alert-time { font-size:11px; color:var(--muted); margin-left:auto; white-space:nowrap; }
    /* verdict */
    .scan-verdict { font-size:13px; font-weight:500; color:var(--ink); line-height:1.55; padding-bottom:10px; border-bottom:1px solid var(--line); margin-bottom:10px; }
    /* urgency pills */
    .urg-now   { border-radius:5px; padding:2px 7px; font-size:10px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; flex-shrink:0; background:rgba(220,38,38,.13); color:#e05252; }
    .urg-watch { border-radius:5px; padding:2px 7px; font-size:10px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; flex-shrink:0; background:rgba(217,119,6,.12);  color:#d97706; }
    .urg-fyi   { border-radius:5px; padding:2px 7px; font-size:10px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; flex-shrink:0; background:var(--surface2);      color:var(--muted); }
    /* scan action items */
    .scan-item { display:flex; align-items:flex-start; gap:10px; padding:8px 0; border-bottom:1px solid var(--line); }
    .scan-item:last-child { border-bottom:none; }
    .scan-item-body { flex:1; min-width:0; }
    .scan-item-title { font-size:12px; font-weight:600; color:var(--ink); }
    .scan-item-detail { font-size:11px; color:var(--muted); margin-top:3px; line-height:1.45; }
    /* raw flags fallback */
    .scan-flags { display:flex; flex-direction:column; gap:2px; }
    .scan-flag-row { display:flex; align-items:baseline; gap:8px; font-size:12px; padding:4px 0; border-bottom:1px solid var(--line); }
    .scan-flag-row:last-child { border-bottom:none; }
    .scan-flag-sym  { font-weight:700; width:42px; flex-shrink:0; }
    .scan-flag-text { color:var(--muted); flex:1; }
    /* ── Proposal / idea cards ── */
    .props-section { border-top:1px solid var(--line); margin-top:14px; padding-top:14px; }
    .ideas-section-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }
    .ideas-section-label { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.09em; color:var(--green); }
    .ideas-budget-tag { font-size:11px; color:var(--muted); background:var(--surface2); border:1px solid var(--line); border-radius:5px; padding:2px 9px; }
    /* ── Pending idea card (redesigned) ── */
    .idea-card {
      background:var(--surface); border:1px solid var(--line);
      border-radius:14px; overflow:hidden; margin-bottom:10px;
      transition:border-color .2s, box-shadow .2s;
      box-shadow:0 1px 3px rgba(0,0,0,.3);
    }
    .idea-card:last-child { margin-bottom:0; }
    .idea-card:hover { border-color:rgba(255,255,255,.15); box-shadow:0 4px 16px rgba(0,0,0,.4); }
    /* Left accent bar showing BUY/SELL */
    .idea-card-accent { width:4px; background:var(--green); flex-shrink:0; }
    .idea-card-inner { display:flex; gap:0; }
    .idea-card-main { flex:1; min-width:0; }
    /* Top row */
    .idea-card-top {
      display:flex; align-items:center; justify-content:space-between;
      padding:14px 18px 10px; gap:12px;
    }
    .idea-card-topleft { display:flex; align-items:center; gap:12px; min-width:0; }
    .idea-sym-block { display:flex; flex-direction:column; }
    .idea-sym { font-size:20px; font-weight:800; letter-spacing:-.03em; line-height:1; color:var(--ink); }
    .idea-sym-sub { font-size:11px; color:var(--muted); margin-top:2px; letter-spacing:.01em; }
    .idea-pills { display:flex; flex-direction:column; gap:4px; }
    .idea-action-pill {
      font-size:10px; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
      border-radius:4px; padding:2px 8px; flex-shrink:0; align-self:flex-start;
    }
    .idea-urgency-pill {
      font-size:10px; font-weight:600; letter-spacing:.05em; text-transform:uppercase;
      border-radius:4px; padding:2px 7px; flex-shrink:0; align-self:flex-start;
    }
    .idea-card-topright { text-align:right; flex-shrink:0; }
    .idea-cost-label { font-size:10px; text-transform:uppercase; letter-spacing:.07em; color:var(--muted); margin-bottom:3px; }
    .idea-cost-val { font-size:20px; font-weight:700; letter-spacing:-.03em; color:var(--ink); line-height:1; }
    /* Divider */
    .idea-div { height:1px; background:var(--line); margin:0 18px; }
    /* Metrics strip */
    .idea-metrics { display:flex; padding:10px 18px; gap:0; }
    .idea-metric { flex:1; padding-right:16px; border-right:1px solid var(--line); margin-right:16px; }
    .idea-metric:last-child { border-right:none; padding-right:0; margin-right:0; }
    .idea-metric-label { font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin-bottom:3px; }
    .idea-metric-val { font-size:13px; font-weight:700; color:var(--ink); letter-spacing:-.01em; }
    /* AI Thesis */
    .idea-thesis { padding:10px 18px 12px; }
    .idea-thesis-label { font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:.07em; color:var(--muted); margin-bottom:5px; opacity:.7; }
    .idea-thesis-text { font-size:13px; color:rgba(232,237,245,0.75); line-height:1.65; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
    .idea-thesis-toggle { background:none; border:none; color:var(--accent); font-size:11px; font-weight:600; cursor:pointer; font-family:inherit; padding:4px 0 0; display:block; opacity:.75; transition:opacity .1s; }
    .idea-thesis-toggle:hover { opacity:1; }
    /* Action buttons */
    .idea-btns { display:flex; border-top:1px solid var(--line); }
    .idea-btn-place {
      flex:1; background:transparent; color:var(--green);
      border:none; border-right:1px solid var(--line);
      padding:13px 18px; font-size:13px; font-weight:700;
      cursor:pointer; font-family:inherit; letter-spacing:-.01em;
      transition:background .15s; display:flex; align-items:center; justify-content:center; gap:7px;
    }
    .idea-btn-place:hover { background:rgba(34,211,90,.07); }
    .idea-btn-place:disabled { opacity:.35; cursor:not-allowed; }
    .idea-btn-sell {
      flex:1; background:transparent; color:var(--red);
      border:none; border-right:1px solid var(--line);
      padding:13px 18px; font-size:13px; font-weight:700;
      cursor:pointer; font-family:inherit; letter-spacing:-.01em;
      transition:background .15s; display:flex; align-items:center; justify-content:center; gap:7px;
    }
    .idea-btn-sell:hover { background:rgba(240,92,82,.07); }
    .idea-btn-pass {
      min-width:90px; background:none; border:none; color:var(--muted);
      padding:13px 16px; font-size:12px; font-weight:500;
      cursor:pointer; font-family:inherit; transition:color .15s, background .15s;
    }
    .idea-btn-pass:hover { background:rgba(240,92,82,.06); color:var(--red); }
    /* Completed / archived cards */
    .props-done { border-top:1px solid var(--line); margin-top:14px; padding-top:14px; display:flex; flex-direction:column; gap:8px; }
    .done-card { border-radius:10px; overflow:hidden; border:1px solid; display:flex; align-items:stretch; }
    .done-card.executed { border-color:rgba(63,185,80,0.2); background:rgba(63,185,80,0.04); }
    .done-card.cancelled { border-color:rgba(255,255,255,0.05); background:rgba(255,255,255,0.015); opacity:.55; }
    .done-card-status { width:3px; flex-shrink:0; }
    .done-card.executed .done-card-status { background:#3fb950; }
    .done-card.cancelled .done-card-status { background:#484f58; }
    .done-card-body { flex:1; padding:10px 14px; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    .done-card-sym { font-size:15px; font-weight:800; letter-spacing:-.02em; }
    .done-card.executed .done-card-sym { color:#3fb950; }
    .done-card.cancelled .done-card-sym { color:var(--muted); }
    .done-card-detail { font-size:11px; color:var(--muted); flex:1; }
    .done-card-detail strong { color:var(--ink); font-weight:600; }
    .done-card-badge { font-size:9.5px; font-weight:700; letter-spacing:.05em; border-radius:5px; padding:2px 7px; flex-shrink:0; }
    .done-card.executed .done-card-badge { background:rgba(63,185,80,0.12); color:#3fb950; }
    .done-card.cancelled .done-card-badge { background:rgba(255,255,255,0.06); color:#6e7681; }
    .btn-review-again { background:none; border:1px solid var(--line); color:var(--muted); border-radius:6px; padding:4px 10px; font-size:11px; font-weight:600; cursor:pointer; font-family:inherit; transition:all .15s; flex-shrink:0; }
    .btn-review-again:hover { border-color:var(--green); color:var(--green); }
    /* dismiss */
    .scan-actions { padding-top:10px; }
    .btn-dismiss { background:none; border:none; color:var(--muted); font-size:12px; cursor:pointer; font-family:inherit; text-decoration:underline; padding:0; opacity:.6; }
    .btn-dismiss:hover { opacity:1; color:var(--ink); }

    /* Drill-down panel */
    html, body { overflow-x: hidden; }
    .drill-panel {
      position: fixed; top: 0; right: 0; bottom: 0; width: 440px;
      background: var(--surface); border-left: 1px solid var(--line);
      display: flex; flex-direction: column; z-index: 201;
      transform: translateX(110%); transition: transform 0.25s ease;
    }
    .drill-panel.open { transform: translateX(0); }
    /* Drag-to-resize / click-to-close edge strip — only active when panel is open */
    .panel-close-strip {
      position: absolute; left: -12px; top: 0; bottom: 0; width: 24px;
      border: none; background: transparent; cursor: col-resize; z-index: 202; padding: 0;
      display: flex; align-items: center; justify-content: center;
      pointer-events: none; opacity: 0;
      transition: opacity 0.2s;
    }
    .drill-panel.open .panel-close-strip { pointer-events: auto; opacity: 1; }
    /* Visible line */
    .panel-close-strip::before {
      content: ''; position: absolute; left: 11px; top: 0; bottom: 0; width: 3px;
      background: var(--line); border-radius: 2px;
      transition: background 0.15s, box-shadow 0.15s, width 0.15s;
    }
    /* Grip dots centred on the line */
    .panel-close-strip::after {
      content: '⋮⋮'; position: absolute; left: 5px;
      font-size: 11px; line-height: 1; letter-spacing: -2px; color: var(--muted);
      opacity: 0; transition: opacity 0.15s;
      pointer-events: none;
    }
    .panel-close-strip:hover::before {
      background: var(--accent); width: 4px;
      box-shadow: -2px 0 10px rgba(15,118,110,0.35);
    }
    .panel-close-strip:hover::after { opacity: 1; }
    .is-resizing .panel-close-strip::after { opacity: 1; }
    .is-resizing { cursor: col-resize !important; user-select: none !important; }
    .drill-header {
      display: flex; align-items: flex-start; justify-content: space-between;
      padding: 16px 18px 12px; border-bottom: 1px solid var(--line); flex-shrink: 0;
    }
    .drill-sym { font-size: 22px; font-weight: 800; letter-spacing: -0.04em; }
    .drill-co  { font-size: 11px; color: var(--muted); margin-top: 3px; }
    .drill-price { font-size: 22px; font-weight: 700; letter-spacing: -0.04em; text-align: right; }
    .drill-day   { font-size: 12px; margin-top: 3px; text-align: right; }
    .drill-overview {
      padding: 12px 18px 14px;
      border-bottom: 1px solid var(--line);
      flex-shrink: 0;
    }
    .drill-overview-subhead {
      font-size: 10px; font-weight: 700; text-transform: uppercase;
      letter-spacing: .09em; color: var(--muted); margin: 10px 0 6px; opacity:.7;
    }
    .drill-scroll { flex: 1; overflow-y: auto; display: flex; flex-direction: column; }
    .period-tabs { display: flex; gap: 4px; padding: 10px 18px; border-bottom: 1px solid var(--line); flex-shrink: 0; }
    .period-tab {
      background: none; border: 1px solid var(--line); color: var(--muted);
      padding: 4px 10px; border-radius: 6px; font-size: 12px; cursor: pointer;
      font-family: inherit; transition: all .15s;
    }
    .period-tab.active { background: var(--accent); border-color: var(--accent); color: white; font-weight: 600; }
    .period-tab:hover:not(.active) { border-color: var(--accent); color: var(--ink); }
    .drill-chart-wrap { padding: 10px 14px 4px; position: relative; height: 200px; flex-shrink: 0; }
    .drill-stats {
      display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
      padding: 14px 18px; border-top: 1px solid var(--line); flex-shrink: 0;
    }
    .dstat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 3px; }
    .dstat-val   { font-size: 14px; font-weight: 600; }
    /* Thesis snapshot — compact redesign */
    .drill-fund { padding: 0; }
    .drill-overview-empty { color: var(--muted); font-size: 12px; padding: 4px 0; }
    /* Tags row: sector + consensus badge */
    .thesis-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; align-items: center; }
    .thesis-tag {
      font-size: 11px; font-weight: 500; padding: 2px 8px;
      border-radius: 5px; background: var(--surface2); color: var(--muted);
      border: 1px solid var(--line); white-space: nowrap;
    }
    .thesis-tag.consensus-buy  { background: rgba(34,211,90,.12);  color: var(--green); border-color: rgba(34,211,90,.2); font-weight:700; }
    .thesis-tag.consensus-hold { background: rgba(245,158,11,.10); color: var(--amber); border-color: rgba(245,158,11,.2); font-weight:700; }
    .thesis-tag.consensus-sell { background: rgba(240,92,82,.12);  color: var(--red);   border-color: rgba(240,92,82,.2);  font-weight:700; }
    /* Target price highlight */
    .thesis-target {
      display: flex; align-items: baseline; gap: 6px;
      padding: 7px 10px; border-radius: 8px;
      background: var(--surface2); border: 1px solid var(--line);
      margin-bottom: 10px;
    }
    .thesis-target-label { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); }
    .thesis-target-price { font-size: 15px; font-weight: 700; color: var(--ink); margin-left: auto; }
    .thesis-target-upside { font-size: 12px; font-weight: 600; }
    /* 2-col metrics table */
    .thesis-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
    .thesis-metric {
      display: flex; flex-direction: column; padding: 6px 0;
      border-bottom: 1px solid var(--line);
    }
    .thesis-metric:nth-last-child(-n+2) { border-bottom: none; }
    .thesis-metric-label { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin-bottom: 3px; }
    .thesis-metric-val   { font-size: 13px; font-weight: 600; color: var(--ink); }
    /* Stop levels */
    .stop-strip { display: grid; grid-template-columns: repeat(3,1fr); gap: 6px; }
    .stop-card {
      padding: 8px 10px; border: 1px solid var(--line);
      border-radius: 8px; background: var(--surface2);
    }
    .stop-card-label { color: var(--muted); font-size: 9.5px; text-transform: uppercase; letter-spacing: .07em; line-height: 1.35; margin-bottom: 4px; }
    .stop-card-value { font-size: 13px; font-weight: 700; }
    @media (max-width: 640px) {
      .drill-overview-head {
        flex-direction: column;
        align-items: flex-start;
      }
      .drill-overview-note {
        max-width: none;
        text-align: left;
      }
    }
    tbody tr { cursor: pointer; }

    /* Advisor chat panel */
    .chat-toggle {
      background: var(--accent);
      color: white;
      border: none;
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      font-family: inherit;
    }
    .chat-panel {
      position: fixed;
      top: 0; right: 0; bottom: 0;
      width: 380px;
      background: var(--surface);
      border-left: 1px solid var(--line);
      display: flex;
      flex-direction: column;
      z-index: 200;
      transform: translateX(110%);
      transition: transform 0.25s ease;
    }
    .chat-panel.open { transform: translateX(0); }
    .chat-panel .panel-close-strip { pointer-events: none; opacity: 0; transition: opacity 0.2s; }
    .chat-panel.open .panel-close-strip { pointer-events: auto; opacity: 1; }
    /* Main content shifts left when a side panel is open */
    main { transition: padding-right 0.25s ease; }
    .chat-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      flex-shrink: 0;
    }
    .chat-title { font-weight: 700; font-size: 14px; }
    .chat-close { background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; padding: 4px; line-height: 1; }
    .chat-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .msg { max-width: 100%; }
    .msg-user { align-self: flex-end; }
    .msg-user .bubble {
      background: var(--accent);
      color: white;
      border-radius: 14px 14px 4px 14px;
      padding: 9px 13px;
      font-size: 13px;
      line-height: 1.5;
      display: inline-block;
      max-width: 300px;
      word-wrap: break-word;
    }
    .msg-assistant .bubble {
      background: var(--surface2);
      color: var(--ink);
      border-radius: 14px 14px 14px 4px;
      padding: 9px 13px;
      font-size: 13px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-wrap: break-word;
    }
    .chat-input-area {
      padding: 12px;
      border-top: 1px solid var(--line);
      display: flex;
      gap: 8px;
      flex-shrink: 0;
    }
    .chat-input {
      flex: 1;
      background: var(--surface2);
      border: 1px solid var(--line);
      color: var(--ink);
      border-radius: 8px;
      padding: 9px 12px;
      font-size: 13px;
      font-family: inherit;
      resize: none;
      outline: none;
      max-height: 120px;
    }
    .chat-input:focus { border-color: var(--accent); }
    .chat-send {
      background: var(--accent);
      color: white;
      border: none;
      border-radius: 8px;
      padding: 0 14px;
      font-size: 18px;
      cursor: pointer;
      flex-shrink: 0;
    }
    .chat-send:disabled { opacity: 0.4; cursor: not-allowed; }
    .typing { color: var(--muted); font-size: 12px; padding: 4px 0; }
    /* Thinking indicator */
    .thinking-wrap {
      display: flex; align-items: center; gap: 10px;
      padding: 10px 13px;
      background: var(--surface2);
      border-radius: 14px 14px 14px 4px;
      font-size: 12px; color: var(--muted);
      min-width: 120px;
    }
    .think-dots {
      display: flex; gap: 4px; flex-shrink: 0;
    }
    .think-dots span {
      width: 6px; height: 6px; border-radius: 50%;
      background: var(--accent);
      animation: thinkBounce 1.1s ease-in-out infinite;
    }
    .think-dots span:nth-child(1) { animation-delay: 0s; }
    .think-dots span:nth-child(2) { animation-delay: 0.18s; }
    .think-dots span:nth-child(3) { animation-delay: 0.36s; }
    @keyframes thinkBounce {
      0%, 60%, 100% { transform: translateY(0); opacity: 0.35; }
      30% { transform: translateY(-5px); opacity: 1; }
    }
    .think-label { font-size: 12px; color: var(--muted); }

    /* Trade Journal */
    .journal-scorecard { display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;padding:14px 18px; }
    .j-stat { background:var(--surface2);border-radius:8px;padding:10px 12px; }
    .j-stat-label { font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px; }
    .j-stat-val { font-size:18px;font-weight:700;letter-spacing:-0.03em; }

    /* News Feed */
    .news-item { padding:12px 18px;border-bottom:1px solid var(--line); }
    .news-item:last-child { border-bottom:none; }
    .news-header { display:flex;align-items:flex-start;gap:8px;margin-bottom:4px; }
    .news-sym { font-size:11px;font-weight:700;background:var(--surface2);border-radius:4px;padding:2px 6px;flex-shrink:0;margin-top:1px; }
    .news-title { font-size:13px;font-weight:500;line-height:1.4;flex:1;color:var(--ink);text-decoration:none; }
    .news-title:hover { color:var(--accent); }
    .news-take { font-size:12px;color:var(--muted);line-height:1.4;padding-left:44px; }
    .news-footer { display:flex;align-items:center;gap:8px;margin-top:5px;font-size:11px;color:var(--muted);padding-left:44px; }
    .news-badge-high   { color:var(--red);font-weight:700; }
    .news-badge-medium { color:#fbbf24;font-weight:700; }
    .news-badge-low    { color:var(--muted); }

    /* Draggable panels */
    #panelsContainer { display:flex; flex-direction:column; gap:14px; }
    /* Top-center drag grip — appears on panel hover */
    .panel-drag-top {
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 22px;
      display: flex;
      justify-content: center;
      align-items: center;
      cursor: grab;
      opacity: 0;
      transition: opacity .18s;
      touch-action: none;
      user-select: none;
      z-index: 5;
    }
    .panel:hover .panel-drag-top { opacity: 1; }
    .panel-drag-top:hover { opacity: 1 !important; }
    .panel-drag-top:active { cursor: grabbing; }
    .panel-drag-top svg { pointer-events: none; }
    .sortable-ghost {
      opacity: 0.3;
      background: var(--surface2) !important;
      border: 2px dashed var(--accent) !important;
    }
    .sortable-chosen { box-shadow: 0 16px 48px rgba(0,0,0,0.6) !important; z-index: 10; }
    .sortable-drag   { box-shadow: 0 20px 60px rgba(0,0,0,0.7) !important; }
    .panel { transition: box-shadow .2s ease; }

    /* ── App shell ── */
    html, body { height:100%; overflow:hidden; }
    .app-shell { display:flex; height:100vh; overflow:hidden; background:var(--bg); }

    /* ── SIDEBAR ── */
    .sidebar {
      width:220px; flex-shrink:0;
      background:var(--surface);
      border-right:1px solid var(--line);
      display:flex; flex-direction:column;
      height:100vh; z-index:50;
    }
    /* Brand */
    .sidebar-brand {
      height:56px; padding:0 18px;
      border-bottom:1px solid var(--line);
      display:flex; align-items:center; gap:10px; flex-shrink:0;
    }
    .sidebar-logo {
      width:28px; height:28px; border-radius:7px; flex-shrink:0;
      background:var(--accent);
      display:flex; align-items:center; justify-content:center;
    }
    .sidebar-logo svg { width:14px; height:14px; color:#fff; }
    .sidebar-brand-text { min-width:0; }
    .sidebar-brand-name {
      font-size:13px; font-weight:700; letter-spacing:-0.02em;
      color:var(--ink); white-space:nowrap; line-height:1.2;
    }
    .sidebar-brand-sub {
      font-size:10px; color:var(--muted); font-weight:400;
      margin-top:1px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    }
    /* Nav */
    .sidebar-nav { flex:1; padding:10px 10px 6px; display:flex; flex-direction:column; gap:1px; overflow-y:auto; }
    .nav-section-label {
      font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:.1em;
      color:var(--dim); padding:12px 10px 5px;
    }
    .nav-item {
      display:flex; align-items:center; gap:9px; padding:8px 10px;
      border-radius:6px; font-size:13px; font-weight:500;
      color:var(--muted); cursor:pointer; text-decoration:none;
      transition:background .12s, color .12s; white-space:nowrap;
      position:relative; user-select:none; line-height:1;
    }
    .nav-item:hover { background:var(--surface2); color:var(--ink); }
    .nav-item.active {
      background:var(--accent-soft); color:var(--accent);
      font-weight:600;
    }
    .nav-item.active::before {
      content:''; position:absolute; left:0; top:50%; transform:translateY(-50%);
      width:2px; height:60%; background:var(--accent); border-radius:0 2px 2px 0;
    }
    .nav-item.featured { color:var(--green); font-weight:600; }
    .nav-item.featured:hover { background:var(--green-soft); }
    .nav-item.featured.active {
      background:var(--green-soft); color:var(--green);
    }
    .nav-item.featured.active::before { background:var(--green); }
    .nav-icon {
      width:16px; height:16px; flex-shrink:0; display:flex;
      align-items:center; justify-content:center; opacity:.6;
    }
    .nav-item:hover .nav-icon,
    .nav-item.active .nav-icon { opacity:1; }
    .nav-icon svg { width:16px; height:16px; }
    .nav-label { flex:1; font-size:13px; }
    .nav-badge {
      background:var(--red); color:white; border-radius:99px;
      padding:1px 5px; font-size:9px; font-weight:700; flex-shrink:0;
      min-width:16px; text-align:center;
    }
    .nav-badge.green { background:var(--green); color:var(--bg); }
    /* Bottom */
    .sidebar-bottom { border-top:1px solid var(--line); padding:8px 10px 14px; display:flex; flex-direction:column; gap:1px; }
    .sidebar-market {
      padding:7px 10px; display:flex; align-items:center; gap:7px;
      font-size:11px; color:var(--muted); font-weight:500;
    }

    /* MAIN AREA */
    .main-area { flex:1; display:flex; flex-direction:column; overflow:hidden; min-width:0; }
    .topbar {
      display:flex; align-items:center; justify-content:space-between;
      padding:0 22px; background:var(--surface); border-bottom:1px solid var(--line);
      flex-shrink:0; gap:16px; height:56px;
    }
    .topbar-left  { display:flex; align-items:center; gap:12px; min-width:0; flex:1; }
    .topbar-right {
      display:flex; align-items:center; gap:8px; flex-shrink:0; flex-wrap:wrap;
      justify-content:flex-end;
    }
    .topbar-kicker { display:none; }
    .topbar-heading { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .topbar-title {
      font-weight:700; font-size:17px; letter-spacing:-0.02em; color:var(--ink);
    }
    .topbar-pill {
      font-size:10px; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
      color:var(--muted); border:1px solid var(--line); border-radius:999px;
      padding:3px 8px;
    }
    .topbar-subtitle { display:none; }

    /* SUMMARY STRIP */
    .summary-strip {
      display:grid; grid-template-columns:repeat(5,1fr);
      border-bottom:1px solid var(--line); flex-shrink:0;
      background:var(--surface);
    }
    .summary-strip .card {
      border-radius:0; border:none; border-right:1px solid var(--line);
      padding:14px 22px; background:transparent;
    }
    .summary-strip .health-card {
      border-radius:0; border:none; background:transparent; padding:14px 22px;
    }
    .summary-strip .card-label {
      font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:.08em;
      color:var(--dim); margin-bottom:7px;
    }
    .summary-strip .card-value {
      font-size:22px; font-weight:700; letter-spacing:-0.04em; line-height:1;
    }
    .summary-strip .card-sub { font-size:11px; margin-top:5px; color:var(--muted); }

    /* PAGES */
    .pages-wrap { flex:1; overflow-y:auto; background:var(--bg); }
    .page { display:none; }
    .page.active { display:block; }
    .page-inner { padding:24px 28px 60px; display:flex; flex-direction:column; gap:14px; max-width:1600px; }
    .panel-helper {
      padding:0 20px 14px; font-size:12px; color:var(--muted); line-height:1.6;
      border-bottom:1px solid var(--line); margin-bottom:0;
    }

    /* BUY SCAN ACTION BAR */
    .scan-hero-bar {
      display:flex; align-items:center; gap:12px; flex-wrap:wrap;
      padding:0 0 16px;
    }
    .scan-hero-copy { display:flex; flex-direction:column; gap:2px; flex:1; min-width:0; }
    .scan-hero-title {
      font-size:11px; font-weight:700; letter-spacing:.09em; text-transform:uppercase;
      color:var(--muted); opacity:.6;
    }
    .scan-hero-note { font-size:12px; color:var(--muted); line-height:1.4; }
    .scan-hero-actions {
      display:flex; align-items:center; gap:8px; flex-wrap:wrap; flex-shrink:0;
    }
    .btn-scan-run {
      background:var(--green); color:#050a0e; border:none; border-radius:8px;
      padding:8px 18px; font-size:12px; font-weight:700; cursor:pointer;
      font-family:inherit; transition:opacity .15s, transform .1s;
      letter-spacing:-.01em;
    }
    .btn-scan-run:hover { opacity:.88; }
    .btn-scan-run:active { transform:scale(.97); }
    .btn-scan-run:disabled { opacity:.35; cursor:not-allowed; }
    .scan-status-text { font-size:11px; color:var(--muted); font-weight:500; }
    /* Sell modal */
    .sell-row { display:flex; align-items:baseline; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--line); }
    .sell-row:last-child { border-bottom:none; }
    .sell-row-label { font-size:12px; color:var(--muted); }
    .sell-row-val { font-size:13px; font-weight:600; color:var(--ink); text-align:right; }
    .sell-tax-section { background:var(--surface2); border-radius:10px; padding:12px 16px; margin:14px 0; }
    .sell-tax-title { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.09em; color:var(--muted); margin-bottom:10px; opacity:.7; }
    .sell-hold-toggle { display:flex; gap:0; border:1px solid var(--line); border-radius:8px; overflow:hidden; margin-bottom:12px; }
    .sell-hold-btn { flex:1; background:none; border:none; color:var(--muted); padding:7px 10px; font-size:12px; font-weight:600; cursor:pointer; font-family:inherit; transition:background .15s, color .15s; text-align:center; }
    .sell-hold-btn.active { background:var(--accent); color:#fff; }
    .sell-net { font-size:22px; font-weight:800; letter-spacing:-.04em; color:var(--green); }
    .sell-input { background:var(--surface2); border:1px solid var(--line); color:var(--ink); border-radius:8px; padding:8px 12px; font-size:15px; font-weight:600; font-family:inherit; outline:none; width:100%; transition:border-color .15s; }
    .sell-input:focus { border-color:var(--accent); }
    .empty-state {
      display:flex; flex-direction:column; align-items:flex-start; gap:10px;
      padding:22px 20px; background:var(--surface); border:1px solid var(--line);
      border-radius:12px;
    }
    .empty-title { font-size:15px; font-weight:700; letter-spacing:-0.02em; color:var(--ink); }
    .empty-body { font-size:12px; color:var(--muted); line-height:1.6; max-width:640px; }
    .empty-actions { display:flex; gap:10px; flex-wrap:wrap; }
    .empty-btn {
      background:none; border:1px solid var(--line); color:var(--ink); border-radius:8px;
      padding:8px 14px; font-size:12px; font-weight:600; cursor:pointer; font-family:inherit;
      transition:background .15s, border-color .15s;
    }
    .empty-btn:hover { background:var(--surface2); border-color:rgba(255,255,255,0.14); }
    .empty-btn-primary { background:var(--accent); border-color:var(--accent); color:white; }
    .empty-btn-primary:hover { background:#2f81f7; border-color:#2f81f7; }

    @media(max-width:1024px) {
      .summary-strip { grid-template-columns:repeat(3,1fr); }
      .summary-strip .card:nth-child(4),
      .summary-strip .card:nth-child(5) { border-top:1px solid var(--line); }
    }
    @media(max-width:900px) {
      .summary-strip { grid-template-columns:repeat(2,1fr); }
      .sidebar { width:52px; }
      .nav-label, .nav-badge, .sidebar-brand-text, .sidebar-market span { display:none; }
      .sidebar-brand { padding:0 12px; justify-content:center; }
      .nav-item { padding:10px; justify-content:center; gap:0; }
      .nav-item.active::before { display:none; }
      .nav-icon { width:18px; height:18px; opacity:.7; }
      .topbar { padding:0 16px; }
      .topbar-right { gap:6px; }
      .scan-hero-actions { margin-left:0; }
      .page-inner { padding:16px 16px 48px; }
    }
    @media(max-width:600px) {
      .summary-strip { grid-template-columns:1fr 1fr; }
      .summary-strip .card { padding:12px 14px; }
      .summary-strip .card-value { font-size:18px; }
      .topbar-pill { display:none; }
    }
  </style>
</head>
<body>
<div id="authBanner" style="display:none;position:fixed;top:0;left:0;right:0;z-index:999;background:#b91c1c;color:#fff;font-size:13px;font-weight:600;text-align:center;padding:9px 16px;letter-spacing:.01em;">
  Schwab session expired &mdash; <a href="/setup" style="color:#fff;text-decoration:underline;">reconnect in Setup &amp; Auth</a>
  <button onclick="$('authBanner').style.display='none'" style="margin-left:16px;background:rgba(255,255,255,.2);border:none;color:#fff;border-radius:4px;padding:2px 8px;cursor:pointer;font-size:12px;">Dismiss</button>
</div>

<div class="app-shell">

<!-- ── SIDEBAR ─────────────────────────────────────────────────── -->
<aside class="sidebar">
  <div class="sidebar-brand">
    <div class="sidebar-logo">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
        <polyline points="16 7 22 7 22 13"/>
      </svg>
    </div>
    <div class="sidebar-brand-text">
      <div class="sidebar-brand-name">Schwab Trader</div>
      <div class="sidebar-brand-sub">AI Portfolio Manager</div>
    </div>
  </div>
  <nav class="sidebar-nav">
    <div class="nav-section-label">Opportunities</div>
    <a class="nav-item featured active" data-page="buyscan" onclick="showPage('buyscan');return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
      </span>
      <span class="nav-label">Opportunities</span>
      <span class="nav-badge green" id="scanBadge" style="display:none;"></span>
    </a>

    <div class="nav-section-label">Portfolio</div>
    <a class="nav-item" data-page="overview" onclick="showPage('overview');return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
          <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
        </svg>
      </span>
      <span class="nav-label">Briefing</span>
    </a>
    <a class="nav-item" data-page="portfolio" onclick="showPage('portfolio');return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="7" width="20" height="14" rx="2"/>
          <path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
          <line x1="12" y1="12" x2="12" y2="16"/><line x1="10" y1="14" x2="14" y2="14"/>
        </svg>
      </span>
      <span class="nav-label">Holdings</span>
    </a>
    <a class="nav-item" data-page="alerts" onclick="showPage('alerts');return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22c1.1 0 2-.9 2-2H10c0 1.1.9 2 2 2z"/>
          <path d="M18.4 10.6C18.4 7 15.6 4 12 4S5.6 7 5.6 10.6c0 5.6-2.6 7.4-2.6 7.4h18s-2.6-1.8-2.6-7.4z"/>
        </svg>
      </span>
      <span class="nav-label">Risk Monitor</span>
      <span class="nav-badge" id="alertBadge" style="display:none;"></span>
    </a>
    <a class="nav-item" data-page="insiders" onclick="showPage('insiders');loadInsiders();return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/>
          <path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>
        </svg>
      </span>
      <span class="nav-label">Insiders</span>
    </a>
    <a class="nav-item" data-page="thesis" onclick="showPage('thesis');loadThesis();return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>
        </svg>
      </span>
      <span class="nav-label">Thesis</span>
      <span class="nav-badge" id="thesisBadge" style="display:none;"></span>
    </a>
    <a class="nav-item" data-page="market" onclick="showPage('market');loadMacro();return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
          <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>
        </svg>
      </span>
      <span class="nav-label">Market</span>
    </a>
    <a class="nav-item" data-page="performance" onclick="showPage('performance');return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="20" x2="18" y2="10"/>
          <line x1="12" y1="20" x2="12" y2="4"/>
          <line x1="6" y1="20" x2="6" y2="14"/>
        </svg>
      </span>
      <span class="nav-label">Performance</span>
    </a>

    <div class="nav-section-label">Tools</div>
    <a class="nav-item" data-page="journal" onclick="showPage('journal');return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
          <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
        </svg>
      </span>
      <span class="nav-label">Journal</span>
    </a>
    <a class="nav-item" data-page="advisor" onclick="toggleChat();return false;" href="#">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
      </span>
      <span class="nav-label">Ask Advisor</span>
    </a>
  </nav>
  <div class="sidebar-bottom">
    <div class="sidebar-market">
      <div class="dot" id="mDot"></div>
      <span id="mStatus">Checking...</span>
    </div>
    <a class="nav-item" href="/customize">
      <span class="nav-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </span>
      <span class="nav-label">Settings</span>
    </a>
  </div>
</aside>

<!-- ── MAIN AREA ────────────────────────────────────────────────── -->
<div class="main-area" id="mainArea">

  <!-- TOPBAR -->
  <div class="topbar">
    <div class="topbar-left">
      <div>
        <div class="topbar-kicker">Trading Workspace</div>
        <div class="topbar-heading">
          <span class="topbar-title" id="topbarTitle">Opportunity Queue</span>
          <span class="topbar-pill" id="topbarPill">Live approvals</span>
        </div>
        <div class="topbar-subtitle" id="topbarSubtitle">Review AI trade ideas, run scans, and only send a live order after preview plus confirmation.</div>
      </div>
    </div>
    <div class="topbar-right">
      <span id="syncAgeLabel" style="font-size:11px;color:var(--muted);display:none;"></span>
      <button class="btn" onclick="openWhatif()" style="font-size:12px;padding:6px 12px;">Scenario Planner</button>
      <a href="/setup" style="color:var(--muted);font-size:12px;padding:6px 10px;border-radius:6px;text-decoration:none;transition:color .15s,background .15s;" onmouseover="this.style.color='var(--ink)';this.style.background='var(--surface2)'" onmouseout="this.style.color='var(--muted)';this.style.background=''">Setup &amp; Auth</a>
    </div>
  </div>

  <div class="error-box" id="errBox"></div>

  <!-- SUMMARY STRIP -->
  <div class="summary-strip">
    <div class="card" onclick="openStatModal('value')">
      <div class="card-label">Portfolio Value</div>
      <div class="card-value" id="cTotal"><span class="skel" style="width:110px;height:26px">&nbsp;</span></div>
      <div class="card-sub" id="cTotalSub">&nbsp;</div>
    </div>
    <div class="card" onclick="openStatModal('day')">
      <div class="card-label">Today's P&L</div>
      <div class="card-value" id="cDay"><span class="skel" style="width:90px;height:26px">&nbsp;</span></div>
      <div class="card-sub" id="cDaySub">&nbsp;</div>
    </div>
    <div class="card" onclick="openStatModal('return')">
      <div class="card-label">Total Return</div>
      <div class="card-value" id="cPnl"><span class="skel" style="width:90px;height:26px">&nbsp;</span></div>
      <div class="card-sub" id="cPnlSub">&nbsp;</div>
    </div>
    <div class="card" onclick="openStatModal('cash')">
      <div class="card-label">Cash Available</div>
      <div class="card-value" id="cCash"><span class="skel" style="width:80px;height:26px">&nbsp;</span></div>
      <div class="card-sub" id="cCashSub">&nbsp;</div>
    </div>
    <div class="health-card" id="healthCard" style="cursor:pointer" onclick="openStatModal('health')">
      <div class="card-label">Portfolio Health</div>
      <div class="health-ring-wrap">
        <svg class="health-ring" width="48" height="48" viewBox="0 0 48 48">
          <circle cx="24" cy="24" r="20" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="5"/>
          <circle id="healthArc" cx="24" cy="24" r="20" fill="none" stroke="#3fb950" stroke-width="5"
            stroke-dasharray="125.66" stroke-dashoffset="125.66"
            stroke-linecap="round" transform="rotate(-90 24 24)"
            style="transition:stroke-dashoffset .8s ease,stroke .4s;"/>
        </svg>
        <div>
          <div class="health-score-num" id="healthScore">—</div>
          <div class="health-label" id="healthLabel">Loading...</div>
        </div>
      </div>
    </div>
  </div>

  <!-- ── Stat drill-down modal ───────────────────────────────── -->
  <div class="stat-overlay" id="statOverlay" onclick="if(event.target===this)closeStatModal()">
    <div class="stat-box">
      <div class="stat-box-head">
        <span class="stat-box-title" id="statTitle"></span>
        <button class="stat-box-close" onclick="closeStatModal()">&#x2715;</button>
      </div>
      <div class="stat-box-body" id="statBody"></div>
    </div>
  </div>

  <!-- ── PAGES ─────────────────────────────────────────────────── -->
  <div class="pages-wrap" id="pagesWrap">

    <!-- BUY SCAN (default page) -->
    <div class="page active" id="page-buyscan">
      <div class="page-inner">
        <div class="scan-hero-bar">
          <div class="scan-hero-copy">
            <div class="scan-hero-title">Opportunity Queue</div>
            <div class="scan-hero-note">AI-researched trade ideas. Nothing executes without your approval.</div>
          </div>
          <div class="scan-hero-actions">
            <span id="agentStatus" class="scan-status-text"></span>
            <button class="btn-scan-run" id="buyCheckBtn" onclick="runBuyScan()">Run Opportunity Scan</button>
          </div>
        </div>
        <div id="scanBody">
          <div class="empty-state">
            <div class="empty-title">Loading opportunity queue...</div>
            <div class="empty-body">Pulling the latest scan results and review status for current trade ideas.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- OVERVIEW -->
    <div class="page" id="page-overview">
      <div class="page-inner">
        <div class="briefing-card" id="briefingCard" style="display:none;">
          <div class="briefing-header">
            <span class="briefing-title">AI Morning Briefing</span>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="briefing-age" id="briefingAge"></span>
              <button class="btn" style="font-size:11px;padding:3px 8px;" onclick="loadBriefing(true)">↺ Refresh</button>
            </div>
          </div>
          <div class="briefing-headline" id="briefingHeadline"></div>
          <div class="briefing-bullets" id="briefingBullets"></div>
          <div class="briefing-footer">
            <span class="briefing-action" id="briefingAction"></span>
            <span class="briefing-watch" id="briefingWatch"></span>
          </div>
        </div>
        <div class="panel" id="newsPanel">
          <div class="panel-header">
            <span class="panel-title">News Feed <span style="font-size:11px;color:var(--muted);font-weight:400;">AI-triaged</span></span>
            <div class="panel-meta">
              <span class="last-updated" id="newsStatus">Loading...</span>
              <button class="btn" onclick="loadNews(true)">&#8635; Refresh</button>
            </div>
          </div>
          <div id="newsBody" style="max-height:560px;overflow-y:auto;">
            <div style="padding:20px;text-align:center;color:var(--muted);font-size:13px;">Loading news...</div>
          </div>
        </div>
      </div>
    </div>

    <!-- PORTFOLIO -->
    <div class="page" id="page-portfolio">
      <div class="page-inner">
        <div class="panel" id="positionsPanel">
          <div class="panel-header">
            <span class="panel-title">Holdings (<span id="posCount">—</span>)</span>
            <div class="panel-meta">
              <span class="last-updated" id="lastUpdated">Loading...</span>
              <button class="btn" id="refreshBtn" onclick="loadDashboard()">↺ Refresh</button>
            </div>
          </div>
          <div class="panel-helper">Click any row to open price history, options, fundamentals, recent news, and the AI quick take for that symbol.</div>
          <table>
            <thead>
              <tr>
                <th data-col="symbol">Symbol</th>
                <th data-col="qty">Shares</th>
                <th data-col="avgCost" class="hide-sm">Avg Cost</th>
                <th data-col="currentPrice">Price</th>
                <th data-col="mktVal">Mkt Value</th>
                <th data-col="costBasis" class="hide-sm">Cost Basis</th>
                <th data-col="dayPnl">Day P&L</th>
                <th data-col="totalPnl">Total P&L</th>
                <th data-col="totalPct">Return</th>
                <th data-col="weight">Weight</th>
                <th style="width:70px;">Action</th>
              </tr>
            </thead>
            <tbody id="posBody">
              <tr class="empty-row"><td colspan="9">Loading positions...</td></tr>
            </tbody>
          </table>
        </div>
        <div class="panel" id="chartsPanel">
          <!-- Row 1: Treemap full width -->
          <div style="border-bottom:1px solid var(--line);">
            <div class="panel-header" style="border-bottom:none;padding-bottom:4px;">
              <span class="panel-title">Portfolio Treemap</span>
              <span class="panel-meta" style="font-size:11px;color:var(--muted)">Size = market value &nbsp;·&nbsp; Color = total return</span>
            </div>
            <div style="padding:8px 16px 16px;">
              <div id="treemapWrap" style="position:relative;width:100%;height:220px;"></div>
            </div>
          </div>
          <!-- Row 2: Bubble + Waterfall -->
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:0;border-bottom:1px solid var(--line);">
            <div style="border-right:1px solid var(--line);">
              <div class="panel-header" style="border-bottom:none;padding-bottom:4px;">
                <span class="panel-title">Weight vs Return</span>
                <span class="panel-meta" style="font-size:10px;color:var(--muted)">Bubble = value</span>
              </div>
              <div style="padding:8px 16px 16px;position:relative;height:260px;">
                <canvas id="bubbleChart"></canvas>
              </div>
            </div>
            <div>
              <div class="panel-header" style="border-bottom:none;padding-bottom:4px;">
                <span class="panel-title">P&amp;L Attribution</span>
                <span class="panel-meta" style="font-size:10px;color:var(--muted)">Contribution to total return</span>
              </div>
              <div style="padding:8px 16px 16px;position:relative;height:260px;">
                <canvas id="waterfallChart"></canvas>
              </div>
            </div>
          </div>
          <!-- Row 3: Day vs All-time + Concentration scatter -->
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:0;">
            <div style="border-right:1px solid var(--line);">
              <div class="panel-header" style="border-bottom:none;padding-bottom:4px;">
                <span class="panel-title">Today vs All-Time P&amp;L</span>
              </div>
              <div style="padding:8px 16px 16px;position:relative;height:260px;">
                <canvas id="pnlChart"></canvas>
              </div>
            </div>
            <div>
              <div class="panel-header" style="border-bottom:none;padding-bottom:4px;">
                <span class="panel-title">Concentration Risk</span>
                <span class="panel-meta" style="font-size:10px;color:var(--muted)">Weight % vs return %</span>
              </div>
              <div style="padding:8px 16px 16px;position:relative;height:260px;">
                <canvas id="scatterChart"></canvas>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ALERTS -->
    <div class="page" id="page-alerts">
      <div class="page-inner">
        <div class="panel" id="agentPanel">
          <div class="panel-header">
            <span class="panel-title">Risk Monitor</span>
            <div class="panel-meta">
              <button class="btn" id="runCheckBtn" onclick="runAgentCheck()" style="font-size:12px;">Run Risk Scan</button>
              <button class="btn" id="runSellScanBtn" onclick="runSellScan()" style="font-size:12px;">Run Sell Scan</button>
              <button class="btn" onclick="loadAgentAlerts()" style="font-size:12px;">↺ Refresh</button>
            </div>
          </div>
          <div class="panel-helper">AI scans your portfolio for concentration risk, earnings traps, downside momentum, and stop-loss breaches. Nothing trades — alerts only.</div>
          <div id="agentBody" style="padding:0 0 4px;">
            <div class="empty-state" style="margin:0 18px 18px;">
              <div class="empty-title">Loading risk monitor...</div>
              <div class="empty-body">Pulling the latest portfolio scan results and alert history.</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- INSIDERS -->
    <div class="page" id="page-insiders">
      <div class="page-inner">
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">Insider &amp; Congressional Trades</span>
            <div class="panel-meta">
              <select id="insiderFilter" class="finput" style="font-size:12px;padding:4px 8px;width:auto;" onchange="filterInsiders()">
                <option value="all">All</option>
                <option value="buy">Buys only</option>
                <option value="sell">Sells only</option>
                <option value="congressional">Congress only</option>
                <option value="corporate">Insiders only</option>
              </select>
              <button class="btn" onclick="loadInsiders()" style="font-size:12px;">↺ Refresh</button>
            </div>
          </div>
          <div class="panel-body" id="insidersBody">
            <div class="empty-state">Click Refresh to load insider and congressional trading activity.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- THESIS TRACKER -->
    <div class="page" id="page-thesis">
      <div class="page-inner">
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">Thesis Tracker</span>
            <div class="panel-meta">
              <button class="btn" id="thesisCheckBtn" onclick="runThesisCheck()" style="font-size:12px;">Run Check</button>
              <button class="btn" onclick="loadThesis()" style="font-size:12px;">↺ Refresh</button>
            </div>
          </div>
          <div class="panel-body" id="thesisBody">
            <div class="empty-state">Click Refresh to load thesis status for your positions.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- MARKET OVERVIEW -->
    <div class="page" id="page-market">
      <div class="page-inner">
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">Market Overview</span>
            <div class="panel-meta">
              <span class="last-updated" id="macroUpdated"></span>
              <button class="btn" onclick="loadMacro()" style="font-size:12px;">↺ Refresh</button>
            </div>
          </div>
          <div class="panel-body" id="macroBody">
            <div class="empty-state">Click Refresh to load market conditions.</div>
          </div>
        </div>
      </div>
    </div>

    <!-- PERFORMANCE -->
    <div class="page" id="page-performance">
      <div class="page-inner">
        <div class="panel" id="perfPanel">
          <div class="panel-header">
            <span class="panel-title">Portfolio Performance</span>
            <div class="panel-meta">
              <span class="last-updated" id="perfStatus"></span>
              <button class="btn" id="perfRebuildBtn" style="font-size:11px;" title="Fetches your full Schwab transaction history">&#8635; Sync History</button>
              <button class="btn" id="perfBackfillBtn" style="font-size:11px;" title="Estimates past values from current holdings">&#8635; Estimate</button>
              <div id="perfPeriods" style="display:flex;gap:4px;">
                <button class="period-btn period-active" data-days="30">1M</button>
                <button class="period-btn" data-days="90">3M</button>
                <button class="period-btn" data-days="180">6M</button>
                <button class="period-btn" data-days="365">1Y</button>
                <button class="period-btn" data-days="1825">ALL</button>
              </div>
            </div>
          </div>
          <div class="panel-helper">Use <strong>Sync History</strong> when you want the truest account curve from Schwab. Use <strong>Estimate</strong> when you just need a faster directional view.</div>
          <div id="perfBody" style="padding:16px;">
            <div style="text-align:center;color:var(--muted);font-size:13px;padding:40px 0;" id="perfPlaceholder">Loading performance data...</div>
            <div id="perfChartWrap" style="display:none;position:relative;height:280px;">
              <canvas id="perfChart"></canvas>
            </div>
            <div id="perfStats" style="display:none;margin-top:16px;"></div>
          </div>
        </div>
        <div class="panel" id="earningsPanel">
          <div class="panel-header">
            <span class="panel-title">Upcoming Earnings</span>
            <span class="last-updated" id="earningsUpdated">Loading...</span>
          </div>
          <div id="earningsBody" style="padding:0 0 4px;">
            <div style="padding:20px;text-align:center;color:var(--muted);font-size:13px;">Loading earnings calendar...</div>
          </div>
        </div>
      </div>
    </div>

    <!-- JOURNAL -->
    <div class="page" id="page-journal">
      <div class="page-inner">
        <div class="panel" id="journalPanel">
          <div class="panel-header">
            <span class="panel-title">
              Trade Journal
              <span id="journalTradeCount" style="font-size:11px;color:var(--muted);margin-left:6px;"></span>
            </span>
            <div class="panel-meta">
              <span class="last-updated" id="journalStatus">Loading...</span>
              <button class="btn" id="journalRebuildBtn" onclick="rebuildTrades()" title="Recalculate completed trades">&#8635; Recalculate</button>
              <button class="btn" id="journalSyncBtn" onclick="syncJournal()" title="Fetch 1 year of orders from Schwab">&#8635; Fetch 1yr</button>
            </div>
          </div>
          <div class="panel-helper">This view reconstructs completed trades from your order history so you can review process quality, not just P&amp;L.</div>
          <div id="journalScorecard" class="journal-scorecard"></div>
          <div id="journalBody" style="overflow-x:auto;">
            <div style="padding:20px;text-align:center;color:var(--muted);font-size:13px;">Loading trade history...</div>
          </div>
        </div>
      </div>
    </div>

  </div><!-- /.pages-wrap -->

  <!-- MODALS (position:fixed, safe anywhere in DOM) -->

  <!-- Unified order ticket — replaces tradeOverlay for proposal execution -->
  <div id="tradeOverlay" onclick="if(event.target===this)closeTradeReview()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:400;align-items:center;justify-content:center;">
    <div style="background:var(--surface);border:1px solid var(--line2);border-radius:16px;width:min(480px,94vw);max-height:92vh;overflow-y:auto;box-shadow:0 32px 80px rgba(0,0,0,.7);">
      <!-- Step indicator -->
      <div style="display:flex;border-bottom:1px solid var(--line);">
        <div id="tStep1Tab" style="flex:1;padding:13px 0;text-align:center;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--accent);border-bottom:2px solid var(--accent);">1 · Enter Order</div>
        <div id="tStep2Tab" style="flex:1;padding:13px 0;text-align:center;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);border-bottom:2px solid transparent;">2 · Review</div>
        <div id="tStep3Tab" style="flex:1;padding:13px 0;text-align:center;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);border-bottom:2px solid transparent;">3 · Placed</div>
      </div>
      <!-- Step 1: Enter -->
      <div id="tStep1">
        <div style="padding:18px 22px 14px;border-bottom:1px solid var(--line);display:flex;align-items:flex-start;justify-content:space-between;">
          <div>
            <div style="font-size:26px;font-weight:800;letter-spacing:-.04em;line-height:1;" id="tSym">—</div>
            <div style="display:flex;align-items:center;gap:7px;margin-top:4px;">
              <span style="font-size:12px;color:var(--muted);" id="tSymName">—</span>
              <span id="tMarketPill" style="display:none;font-size:9px;font-weight:700;padding:2px 7px;border-radius:100px;letter-spacing:.07em;text-transform:uppercase;"></span>
            </div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:22px;font-weight:700;letter-spacing:-.03em;" id="tPrice">—</div>
            <div style="font-size:12px;font-weight:600;margin-top:2px;" id="tChange">—</div>
          </div>
        </div>
        <!-- Quote strip -->
        <div id="tQuoteStrip" style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0;border-bottom:1px solid var(--line);background:var(--surface2);">
          <div style="padding:9px 14px;border-right:1px solid var(--line);">
            <div style="font-size:9.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);margin-bottom:2px;">Bid</div>
            <div style="font-size:12px;font-weight:600;color:var(--ink);" id="tBid">—</div>
          </div>
          <div style="padding:9px 14px;border-right:1px solid var(--line);">
            <div style="font-size:9.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);margin-bottom:2px;">Ask</div>
            <div style="font-size:12px;font-weight:600;color:var(--ink);" id="tAsk">—</div>
          </div>
          <div style="padding:9px 14px;border-right:1px solid var(--line);">
            <div style="font-size:9.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);margin-bottom:2px;">Day Range</div>
            <div style="font-size:11px;font-weight:600;color:var(--ink);" id="tDayRange">—</div>
          </div>
          <div style="padding:9px 14px;">
            <div style="font-size:9.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);margin-bottom:2px;">52-Week</div>
            <div style="font-size:11px;font-weight:600;color:var(--ink);" id="t52Wk">—</div>
          </div>
        </div>
        <div style="padding:18px 22px;">
          <!-- AI reasoning (from proposal) -->
          <div id="tAiReasoning" style="display:none;background:var(--surface2);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;padding:10px 14px;font-size:12px;line-height:1.6;color:var(--muted);margin-bottom:16px;"></div>
          <!-- Order form -->
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px;">
            <div>
              <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px;">Shares</div>
              <div style="display:flex;align-items:center;gap:0;border:1px solid var(--line);border-radius:8px;overflow:hidden;">
                <button id="tQtyMinus" type="button" style="width:36px;height:38px;background:var(--surface2);border:none;color:var(--ink);font-size:18px;cursor:pointer;font-family:inherit;flex-shrink:0;">−</button>
                <input type="number" id="tQtyInput" min="1" step="1" style="flex:1;background:transparent;border:none;color:var(--ink);font-size:15px;font-weight:700;text-align:center;padding:0;outline:none;font-family:inherit;width:0;">
                <button id="tQtyPlus" type="button" style="width:36px;height:38px;background:var(--surface2);border:none;color:var(--ink);font-size:18px;cursor:pointer;font-family:inherit;flex-shrink:0;">+</button>
              </div>
              <div style="font-size:10.5px;color:var(--muted);margin-top:4px;" id="tQtyContext"></div>
            </div>
            <div>
              <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px;">Order Type</div>
              <div style="display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;">
                <button id="tLimitBtn" type="button" data-otype="LIMIT" style="flex:1;padding:10px 0;background:var(--accent);color:white;border:none;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;transition:background .15s;">Limit</button>
                <button id="tMarketBtn" type="button" data-otype="MARKET" style="flex:1;padding:10px 0;background:transparent;color:var(--muted);border:none;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;transition:background .15s;">Market</button>
              </div>
            </div>
          </div>
          <div id="tLimitRow" style="margin-bottom:14px;">
            <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px;">Limit Price</div>
            <div style="display:flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:8px;padding:0 12px;background:var(--surface2);">
              <span style="color:var(--muted);font-size:14px;">$</span>
              <input type="number" id="tLimitInput" step="0.01" style="flex:1;background:transparent;border:none;color:var(--ink);font-size:15px;font-weight:600;padding:9px 0;outline:none;font-family:inherit;">
            </div>
          </div>
          <!-- Estimated total -->
          <div style="display:flex;align-items:baseline;justify-content:space-between;padding:10px 14px;background:var(--surface2);border-radius:8px;margin-bottom:16px;">
            <span style="font-size:12px;color:var(--muted);">Estimated Total</span>
            <span style="font-size:20px;font-weight:800;letter-spacing:-.04em;" id="tEstTotal">—</span>
          </div>
          <!-- Tax calculator (SELL only) -->
          <div id="tTaxSection" style="display:none;background:var(--surface2);border-radius:8px;padding:12px 14px;margin-bottom:14px;">
            <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:10px;">Tax Estimate</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px 0;font-size:12px;line-height:1.9;">
              <span style="color:var(--muted);">Proceeds</span><span id="tTaxProceeds" style="font-weight:600;text-align:right;">—</span>
              <span style="color:var(--muted);">Gain / Loss</span><span id="tTaxGain" style="font-weight:600;text-align:right;">—</span>
              <span style="color:var(--muted);">Est. Tax</span><span id="tTaxOwed" style="font-weight:600;text-align:right;">—</span>
              <span style="color:var(--muted);font-weight:700;">Net After Tax</span><span id="tTaxNet" style="font-weight:700;text-align:right;">—</span>
            </div>
            <div style="display:flex;gap:8px;margin-top:10px;align-items:center;">
              <span style="font-size:10px;color:var(--dim);">Hold type:</span>
              <button id="tHoldLT" type="button" style="font-size:11px;padding:3px 10px;border-radius:5px;border:1px solid var(--accent);background:var(--accent);color:white;cursor:pointer;font-family:inherit;">Long-term</button>
              <button id="tHoldST" type="button" style="font-size:11px;padding:3px 10px;border-radius:5px;border:1px solid var(--line);background:transparent;color:var(--muted);cursor:pointer;font-family:inherit;">Short-term</button>
            </div>
          </div>
          <!-- AI sell advice panel (SELL only) -->
          <div id="tAiSellBtn" style="display:none;margin-bottom:14px;">
            <button type="button" id="tGetAiBtn" onclick="_otGetAiAdvice()" style="width:100%;background:rgba(37,99,235,.08);border:1px solid rgba(37,99,235,.25);color:#93c5fd;border-radius:8px;padding:9px 14px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;display:flex;align-items:center;justify-content:center;gap:7px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>Get AI Recommendation</button>
            <div id="tAiLoading" style="display:none;padding:10px 0;text-align:center;font-size:12px;color:var(--muted);">Analyzing with Claude...</div>
            <div id="tAiResult" style="display:none;background:var(--surface2);border-radius:8px;padding:12px 14px;margin-top:8px;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:7px;">
                <span id="tAiAction" style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;letter-spacing:.05em;"></span>
                <span id="tAiHeadline" style="font-size:12px;font-weight:600;color:var(--ink);"></span>
              </div>
              <div id="tAiReasoning2" style="font-size:11.5px;color:var(--muted);line-height:1.55;margin-bottom:8px;"></div>
              <div id="tAiRisk" style="display:none;font-size:11px;color:#fbbf24;margin-bottom:8px;"></div>
              <button type="button" id="tAiApplyBtn" onclick="_otApplyAiAdvice()" style="display:none;background:var(--accent);color:white;border:none;border-radius:6px;padding:6px 12px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;"></button>
            </div>
          </div>
          <!-- Status -->
          <div id="tStep1Status" style="min-height:14px;font-size:11.5px;color:var(--red);margin-bottom:14px;"></div>
          <!-- Actions -->
          <div style="display:flex;gap:10px;">
            <button type="button" onclick="closeTradeReview()" style="flex:1;background:none;border:1px solid var(--line);color:var(--muted);padding:11px 0;border-radius:8px;font-size:13px;cursor:pointer;font-family:inherit;">Cancel</button>
            <button type="button" id="tReviewBtn" onclick="tradeGoReview()" style="flex:2;background:var(--accent);color:white;border:none;padding:11px 0;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit;">Review Order</button>
          </div>
        </div>
      </div>
      <!-- Step 2: Review -->
      <div id="tStep2" style="display:none;padding:22px;">
        <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.09em;margin-bottom:8px;">Order Summary</div>
        <div style="font-size:22px;font-weight:800;letter-spacing:-.04em;margin-bottom:6px;" id="tReviewHeadline">—</div>
        <div style="font-size:13px;color:var(--muted);margin-bottom:20px;" id="tReviewMeta">—</div>
        <div style="background:var(--surface2);border-radius:10px;padding:14px 16px;margin-bottom:16px;" id="tReviewRows"></div>
        <div id="tMarketWarning" style="display:none;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:8px;padding:10px 14px;font-size:11.5px;color:#fcd34d;margin-bottom:12px;" id="tMarketWarning"></div>
        <div style="background:rgba(239,68,68,.07);border:1px solid rgba(239,68,68,.2);border-radius:8px;padding:10px 14px;font-size:11.5px;color:#fca5a5;margin-bottom:18px;">
          This places a <strong>real order</strong> on your Schwab account. Schwab will run a preview before execution.
        </div>
        <div id="tStep2Status" style="min-height:14px;font-size:11.5px;color:var(--muted);margin-bottom:14px;"></div>
        <div style="display:flex;gap:10px;">
          <button type="button" onclick="tradeGoBack()" style="flex:1;background:none;border:1px solid var(--line);color:var(--muted);padding:11px 0;border-radius:8px;font-size:13px;cursor:pointer;font-family:inherit;">Back</button>
          <button type="button" id="tPlaceBtn" onclick="confirmTrade()" style="flex:2;background:var(--accent);color:white;border:none;padding:11px 0;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit;">Place Order</button>
        </div>
      </div>
      <!-- Step 3: Placed -->
      <div id="tStep3" style="display:none;padding:40px 22px;text-align:center;">
        <div style="width:52px;height:52px;border-radius:50%;background:var(--green-soft);display:flex;align-items:center;justify-content:center;margin:0 auto 16px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        </div>
        <div style="font-size:18px;font-weight:800;letter-spacing:-.03em;margin-bottom:6px;" id="tStep3Headline">Order Placed</div>
        <div style="font-size:13px;color:var(--muted);line-height:1.6;" id="tStep3Detail"></div>
        <button type="button" onclick="closeTradeReview()" style="margin-top:24px;background:var(--surface2);border:1px solid var(--line);color:var(--ink);padding:10px 28px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;">Done</button>
      </div>
    </div>
  </div>

  <!-- SELL MODAL -->
  <!-- sellOverlay removed — sell flow now uses unified order ticket (tradeOverlay) -->

  <div id="whatifOverlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:300;align-items:center;justify-content:center;">
    <div style="background:var(--surface);border:1px solid var(--line);border-radius:16px;width:min(640px,92vw);max-height:82vh;display:flex;flex-direction:column;">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:18px 22px;border-bottom:1px solid var(--line);">
        <span style="font-weight:700;font-size:15px;">Scenario Planner</span>
        <button onclick="closeWhatif()" style="background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;line-height:1;">&#x2715;</button>
      </div>
      <div style="padding:16px 22px;border-bottom:1px solid var(--line);display:flex;gap:10px;">
        <input id="whatifInput" type="text" placeholder='e.g. "What happens if I add $2,000 to NVDA and trim TSLA?"'
          style="flex:1;background:var(--surface2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:9px 12px;font-size:13px;font-family:inherit;outline:none;"
          onkeydown="if(event.key==='Enter')runWhatif()">
        <button onclick="runWhatif()" style="background:var(--accent);color:white;border:none;border-radius:8px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;white-space:nowrap;">Ask</button>
      </div>
      <div id="whatifResult" style="flex:1;overflow-y:auto;padding:18px 22px;font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--ink);">
        Describe a possible trade, rebalance, or cash move and the advisor will reason through it using your live portfolio.
      </div>
    </div>
  </div>

  <div id="briefOverlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:300;align-items:center;justify-content:center;">
    <div style="background:var(--surface);border:1px solid var(--line);border-radius:16px;width:min(680px,92vw);max-height:80vh;display:flex;flex-direction:column;">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--line);">
        <span style="font-weight:700;font-size:15px;" id="briefTitle">Pre-Earnings Brief</span>
        <button onclick="closeBrief()" style="background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;line-height:1;">&#x2715;</button>
      </div>
      <div id="briefContent" style="overflow-y:auto;padding:20px;font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--ink);flex:1;"></div>
    </div>
  </div>

</div><!-- /.main-area -->
</div><!-- /.app-shell -->

<!-- Position drill-down panel -->
<div class="drill-panel" id="drillPanel">
  <button class="panel-close-strip" id="drillCloseEdge" title="Close panel (click edge)"></button>
  <div class="drill-header">
    <div>
      <div class="drill-sym" id="drillSym">—</div>
      <div class="drill-co"  id="drillCo"></div>
    </div>
    <div style="flex:1;padding:0 12px;">
      <div class="drill-price" id="drillPrice"></div>
      <div class="drill-day"   id="drillDay"></div>
    </div>
    <button onclick="closeDrill()" style="background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;padding:2px 4px;line-height:1;flex-shrink:0;">&times;</button>
  </div>
  <div class="drill-overview">
    <div class="drill-fund" id="drillFund"><div class="drill-overview-empty">Loading…</div></div>
  </div>
  <div class="drill-scroll">
    <div class="period-tabs" id="periodTabs">
      <button class="period-tab" data-pt="day"   data-p="1" data-ft="minute" data-f="5">1D</button>
      <button class="period-tab" data-pt="day"   data-p="5" data-ft="minute" data-f="30">1W</button>
      <button class="period-tab active" data-pt="month"  data-p="1" data-ft="daily"  data-f="1">1M</button>
      <button class="period-tab" data-pt="month"  data-p="3" data-ft="daily"  data-f="1">3M</button>
      <button class="period-tab" data-pt="year"   data-p="1" data-ft="weekly" data-f="1">1Y</button>
    </div>
    <div class="drill-chart-wrap"><canvas id="drillChart"></canvas></div>
    <div class="drill-stats" id="drillStats"></div>
    <div style="border-top:1px solid var(--line);padding:10px 18px 14px;">
      <button id="drillOptionsBtn" class="btn" style="width:100%;text-align:center;">&#9660; Options Chain</button>
      <div id="drillOptionsWrap" style="display:none;margin-top:10px;overflow-x:auto;max-height:260px;overflow-y:auto;"></div>
    </div>
    <!-- AI Quick Take -->
    <div class="quick-take-wrap" id="quickTakeWrap">
      <div class="quick-take-header">
        <span class="quick-take-label">AI Take</span>
        <span class="quick-take-signal" id="quickTakeSignal" style="display:none;"></span>
      </div>
      <div class="quick-take-text" id="quickTakeText" style="color:var(--muted);font-size:12px;">Click a position to load AI analysis.</div>
    </div>
    <div style="border-top:1px solid var(--line);">
      <div style="padding:10px 18px 6px;display:flex;align-items:center;justify-content:space-between;">
        <span style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);">Latest News</span>
        <span id="drillNewsStatus" style="font-size:11px;color:var(--muted);"></span>
      </div>
      <div id="drillNewsBody"></div>
    </div>
  </div><!-- /.drill-scroll -->
</div>

<div class="chat-panel" id="chatPanel">
  <button class="panel-close-strip" id="chatCloseEdge" title="Close panel (click edge)"></button>
  <div class="chat-header">
    <span class="chat-title">Ask Advisor</span>
    <button class="chat-close" onclick="toggleChat()">&times;</button>
  </div>
  <div class="chat-messages" id="chatMessages">
    <div class="msg msg-assistant"><div class="bubble">I have your live portfolio loaded. Ask about positions, concentration, exits, possible trims, or what a new trade would do to the account.</div></div>
  </div>
  <div class="chat-input-area">
    <textarea class="chat-input" id="chatInput" placeholder="Ask about a holding, a risk question, or a scenario..." rows="1"></textarea>
    <button class="chat-send" id="chatSend" onclick="sendMessage()">&uarr;</button>
  </div>
</div>

<script>
  const $ = id => document.getElementById(id);
  const usd = (n, d=2) => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:d,maximumFractionDigits:d}).format(n);
  const num = (n, d=2) => new Intl.NumberFormat('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}).format(n);
  const pct = n => (n>=0?'+':'')+num(n)+'%';
  const gc = n => n>=0?'gain':'loss';
  const span = (cls,txt) => '<span class="'+cls+'">'+txt+'</span>';

  let positions = [];
  let sortCol = 'mktVal';
  let sortDir = 'desc';
  let loading = false;
  let _lastDataFetchTs = 0;
  let demoMode = false;

  // ── Demo mode ────────────────────────────────────────────────────
  const DEMO_POSITIONS = [
    { symbol:'NVDA',  qty:29,  avgCost:98.50,  currentPrice:108.40, mktVal:3143.60,  costBasis:2856.50, totalPnl:287.10,  totalPct:10.05, dayPnl:89.90,   dayPct:2.94,  weight:0 },
    { symbol:'SOXX',  qty:20,  avgCost:195.20, currentPrice:218.40, mktVal:4368.00,  costBasis:3904.00, totalPnl:464.00,  totalPct:11.88, dayPnl:195.00,  dayPct:4.67,  weight:0 },
    { symbol:'QQQ',   qty:8,   avgCost:440.00, currentPrice:478.20, mktVal:3825.60,  costBasis:3520.00, totalPnl:305.60,  totalPct:8.68,  dayPnl:142.40,  dayPct:3.87,  weight:0 },
    { symbol:'MSFT',  qty:3,   avgCost:380.00, currentPrice:421.50, mktVal:1264.50,  costBasis:1140.00, totalPnl:124.50,  totalPct:10.92, dayPnl:38.10,   dayPct:3.10,  weight:0 },
    { symbol:'GOOG',  qty:5,   avgCost:155.00, currentPrice:168.40, mktVal:842.00,   costBasis:775.00,  totalPnl:67.00,   totalPct:8.65,  dayPnl:32.50,   dayPct:4.02,  weight:0 },
    { symbol:'TSM',   qty:3,   avgCost:168.00, currentPrice:182.50, mktVal:547.50,   costBasis:504.00,  totalPnl:43.50,   totalPct:8.63,  dayPnl:18.30,   dayPct:3.46,  weight:0 },
    { symbol:'KLAC',  qty:1,   avgCost:680.00, currentPrice:752.30, mktVal:752.30,   costBasis:680.00,  totalPnl:72.30,   totalPct:10.63, dayPnl:28.40,   dayPct:3.92,  weight:0 },
    { symbol:'AAPL',  qty:4,   avgCost:175.00, currentPrice:195.80, mktVal:783.20,   costBasis:700.00,  totalPnl:83.20,   totalPct:11.89, dayPnl:24.80,   dayPct:3.27,  weight:0 },
    { symbol:'AMAT',  qty:2,   avgCost:172.00, currentPrice:186.40, mktVal:372.80,   costBasis:344.00,  totalPnl:28.80,   totalPct:8.37,  dayPnl:14.60,   dayPct:4.08,  weight:0 },
    { symbol:'META',  qty:1,   avgCost:490.00, currentPrice:548.20, mktVal:548.20,   costBasis:490.00,  totalPnl:58.20,   totalPct:11.88, dayPnl:22.40,   dayPct:4.26,  weight:0 },
    { symbol:'BABA',  qty:3,   avgCost:98.00,  currentPrice:114.20, mktVal:342.60,   costBasis:294.00,  totalPnl:48.60,   totalPct:16.53, dayPnl:12.30,   dayPct:3.73,  weight:0 },
    { symbol:'PLTR',  qty:1,   avgCost:28.50,  currentPrice:92.40,  mktVal:92.40,    costBasis:28.50,   totalPnl:63.90,   totalPct:224.21,dayPnl:4.20,    dayPct:4.76,  weight:0 },
    { symbol:'AMD',   qty:6,   avgCost:119.00, currentPrice:98.40,  mktVal:590.40,   costBasis:714.00,  totalPnl:-123.60, totalPct:-17.31,dayPnl:-18.00,  dayPct:-2.96, weight:0 },
    { symbol:'MU',    qty:2,   avgCost:108.00, currentPrice:94.20,  mktVal:188.40,   costBasis:216.00,  totalPnl:-27.60,  totalPct:-12.78,dayPnl:-6.40,   dayPct:-3.29, weight:0 },
    { symbol:'HSY',   qty:2,   avgCost:162.00, currentPrice:148.30, mktVal:296.60,   costBasis:324.00,  totalPnl:-27.40,  totalPct:-8.46, dayPnl:-3.20,   dayPct:-1.07, weight:0 },
    { symbol:'XLK',   qty:6,   avgCost:198.00, currentPrice:218.60, mktVal:1311.60,  costBasis:1188.00, totalPnl:123.60,  totalPct:10.40, dayPnl:48.60,   dayPct:3.85,  weight:0 },
    { symbol:'AMZN',  qty:1,   avgCost:188.00, currentPrice:194.50, mktVal:194.50,   costBasis:188.00,  totalPnl:6.50,    totalPct:3.46,  dayPnl:7.80,    dayPct:4.18,  weight:0 },
    { symbol:'TSLA',  qty:6,   avgCost:298.00, currentPrice:242.80, mktVal:1456.80,  costBasis:1788.00, totalPnl:-331.20, totalPct:-18.52,dayPnl:-48.00,  dayPct:-3.19, weight:0 },
  ];
  const DEMO_SUMMARY = { liq: 127450.00, cash: 3200.00, totalDay: 2840.00, dayPct: 2.28, totalPnl: 8640.00, totalPct: 7.27 };

  function _loadDemoData() {
    const eq = DEMO_POSITIONS.filter(p=>p.costBasis>0).reduce((s,p)=>s+p.mktVal,0);
    DEMO_POSITIONS.forEach(p => { p.weight = eq > 0 ? p.mktVal/eq*100 : 0; });
    positions = DEMO_POSITIONS.map(p => ({...p}));
    $('cTotal').textContent = usd(DEMO_SUMMARY.liq);
    $('cTotalSub').textContent = positions.length + ' positions  \u2022  ' + usd(DEMO_SUMMARY.cash) + ' cash';
    $('cDay').innerHTML = span(gc(DEMO_SUMMARY.totalDay), usd(DEMO_SUMMARY.totalDay));
    $('cDaySub').innerHTML = span(gc(DEMO_SUMMARY.totalDay), pct(DEMO_SUMMARY.dayPct)) + ' today';
    $('cPnl').innerHTML = span(gc(DEMO_SUMMARY.totalPnl), usd(DEMO_SUMMARY.totalPnl));
    $('cPnlSub').innerHTML = span(gc(DEMO_SUMMARY.totalPnl), pct(DEMO_SUMMARY.totalPct)) + ' all-time';
    $('cCash').textContent = usd(DEMO_SUMMARY.cash);
    $('cCashSub').textContent = 'available to trade';
    $('posCount').textContent = positions.length;
    _lastDataFetchTs = Date.now();
    updateHealthScore(positions);
    const _lu = $('lastUpdated'); if (_lu) _lu.textContent = 'Demo Mode';
    renderTable();
    updateCharts(positions);
  }

  function toggleDemoMode() {
    demoMode = !demoMode;
    const btn = $('demoToggleBtn');
    if (demoMode) {
      btn.textContent = 'Exit Demo';
      btn.style.background = 'rgba(251,191,36,0.25)';
      btn.style.color = '#fbbf24';
      btn.style.border = '1px solid rgba(251,191,36,0.5)';
      _loadDemoData();
    } else {
      btn.textContent = 'Demo Mode';
      btn.style.background = 'rgba(251,191,36,0.1)';
      btn.style.color = '#fbbf24';
      btn.style.border = '1px solid rgba(251,191,36,0.25)';
      loadDashboard();
    }
  }
  let perfChartInst = null;
  let activePerfDays = 30;

  // Session cookie is sent automatically by the browser on every request.
  // 401 means the session expired — show the auth banner.
  async function apiFetch(url, opts = {}) {
    const r = await fetch(url, opts);
    if (r.status === 401) {
      $('authBanner').style.display = '';
      document.body.style.marginTop = '40px'; // shift content below the banner
    }
    return r;
  }

  function _updateSyncAge() {
    const el = $('syncAgeLabel');
    if (!el || !_lastDataFetchTs) return;
    const sec = Math.floor((Date.now() - _lastDataFetchTs) / 1000);
    const min = Math.floor(sec / 60);
    let label;
    if (sec < 60) label = 'Live';
    else if (min < 60) label = 'Data ' + min + 'm ago';
    else label = 'Data ' + Math.floor(min/60) + 'h ago';
    el.textContent = label;
    el.style.display = '';
    // Colour: green if <2m, amber if <10m, muted otherwise
    el.style.color = sec < 120 ? 'var(--green)' : sec < 600 ? '#fbbf24' : 'var(--muted)';
  }
  setInterval(_updateSyncAge, 30000);

  async function loadDashboard() {
    if (demoMode) { _loadDemoData(); return; }
    if (loading) return;
    loading = true;
    const _rb = $('refreshBtn'); if (_rb) _rb.disabled = true;
    const _eb = $('errBox'); if (_eb) _eb.style.display = 'none';

    try {
      const resp = await apiFetch('/api/v1/schwab/accounts?fields=positions');
      if (resp.status === 401) throw new Error('Session expired \u2014 reconnect Schwab in Setup & Auth.');
      if (!resp.ok) throw new Error('Failed to load account data (HTTP '+resp.status+')');
      const accounts = await resp.json();
      if (!accounts || !accounts.length) throw new Error('No accounts returned.');

      const acct = accounts[0].securitiesAccount || {};
      const bal = acct.currentBalances || acct.initialBalances || {};
      const raw = acct.positions || [];

      // Sum liquidation values across all accounts (brokerage + checking)
      const totalLiqAllAccounts = accounts.reduce((s, a) => {
        const b = a.securitiesAccount?.currentBalances || a.securitiesAccount?.initialBalances || {};
        return s + (b.liquidationValue || 0);
      }, 0);
      const checkingBalance = accounts.slice(1).reduce((s, a) => {
        const b = a.securitiesAccount?.currentBalances || a.securitiesAccount?.initialBalances || {};
        return s + (b.liquidationValue || b.cashBalance || 0);
      }, 0);

      positions = raw.map(p => {
        const qty = (p.longQuantity || 0) - (p.shortQuantity || 0);
        const avgCost = p.averagePrice || 0;
        const mktVal = p.marketValue || 0;
        const costBasis = Math.abs(qty) * avgCost;
        const totalPnl = mktVal - costBasis;
        const totalPct = costBasis > 0 ? (totalPnl / costBasis) * 100 : 0;
        const dayPnl = p.currentDayProfitLoss || 0;
        const dayPct = p.currentDayProfitLossPercentage || 0;
        const currentPrice = Math.abs(qty) > 0 ? mktVal / Math.abs(qty) : 0;
        return { symbol: p.instrument?.symbol || '?', qty, avgCost, currentPrice, mktVal, costBasis, totalPnl, totalPct, dayPnl, dayPct, weight: 0 };
      });

      // Compute portfolio weights
      const equityTotal = positions.filter(p => p.costBasis > 0).reduce((s,p) => s+p.mktVal, 0);
      positions.forEach(p => { p.weight = equityTotal > 0 ? p.mktVal / equityTotal * 100 : 0; });

      // Override dayPnl using quotes API — currentDayProfitLoss from positions is unreliable
      // (Schwab sometimes returns total unrealized P&L instead of today's change)
      try {
        const syms = positions.filter(p => p.symbol !== '?').map(p => p.symbol).join(',');
        if (syms) {
          const qr = await apiFetch('/api/v1/schwab/quotes?symbols=' + encodeURIComponent(syms));
          if (qr.ok) {
            const qdata = await qr.json();
            positions.forEach(p => {
              const q = qdata[p.symbol]?.quote;
              if (!q) return;
              const netChg = q.netChange ?? q.regularMarketNetChange;
              if (netChg != null) {
                p.dayPnl = netChg * Math.abs(p.qty);
                const netPct = q.netPercentChangeInDouble;
                p.dayPct = netPct != null ? netPct : p.dayPct;
              }
            });
          }
        }
      } catch (_) { /* keep positions dayPnl as-is on quote fetch failure */ }

      const totalMkt = positions.reduce((s,p)=>s+p.mktVal, 0);
      const totalCost = positions.reduce((s,p)=>s+p.costBasis, 0);
      const totalPnl = totalMkt - totalCost;
      const totalPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
      const totalDay = positions.reduce((s,p)=>s+p.dayPnl, 0);
      const cash = (bal.cashAvailableForTrading || 0) + checkingBalance;
      const liq = totalLiqAllAccounts || (totalMkt + cash);
      const dayPctPort = (liq - totalDay) > 0 ? (totalDay / (liq - totalDay)) * 100 : 0;

      $('cTotal').textContent = usd(liq);
      $('cTotalSub').textContent = positions.length + ' positions  •  '+usd(cash)+' cash';
      $('cDay').innerHTML = span(gc(totalDay), usd(totalDay));
      $('cDaySub').innerHTML = span(gc(totalDay), pct(dayPctPort))+' today';
      $('cPnl').innerHTML = span(gc(totalPnl), usd(totalPnl));
      $('cPnlSub').innerHTML = span(gc(totalPct), pct(totalPct))+' all-time';
      $('cCash').textContent = usd(cash);
      $('cCashSub').textContent = 'available to trade';
      $('posCount').textContent = positions.length;
      _lastDataFetchTs = Date.now();
      updateHealthScore(positions);
      const _lu = $('lastUpdated'); if (_lu) _lu.textContent = 'Updated '+new Date().toLocaleTimeString();
      _updateSyncAge();

      renderTable();
      updateCharts(positions);
      loadNews();  // uses positions; throttled internally
    } catch(e) {
      const _eb2 = $('errBox');
      if (_eb2) { _eb2.textContent = e.message; _eb2.style.display = 'block'; }
      const _lu2 = $('lastUpdated'); if (_lu2) _lu2.textContent = 'Failed';
    } finally {
      loading = false;
      const _rb2 = $('refreshBtn'); if (_rb2) _rb2.disabled = false;
    }
  }

  const maxAbs = arr => Math.max(...arr.map(p => Math.abs(p.totalPnl)), 1);

  function renderTable() {
    const sorted = [...positions].sort((a,b) => {
      const av=a[sortCol], bv=b[sortCol];
      if (typeof av==='string') return sortDir==='asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir==='asc' ? av-bv : bv-av;
    });

    const mx = maxAbs(sorted);

    $('posBody').innerHTML = sorted.length ? sorted.map(p => {
      const barW = Math.round(Math.min(Math.abs(p.totalPnl)/mx*80, 80));
      const barCls = p.totalPnl >= 0 ? 'bar-pos' : 'bar-neg';
      const qtyFmt = p.qty % 1 === 0 ? num(p.qty,0) : num(p.qty,4);
      const heatBg = p.totalPct >= 20 ? 'rgba(63,185,80,0.10)'
                   : p.totalPct >= 5  ? 'rgba(63,185,80,0.05)'
                   : p.totalPct <= -20 ? 'rgba(248,81,73,0.10)'
                   : p.totalPct <= -5  ? 'rgba(248,81,73,0.05)'
                   : '';
      return '<tr data-sym="'+p.symbol+'" style="'+(heatBg?'background:'+heatBg+';':'')+'">'
        +'<td><span class="sym">'+p.symbol+'</span></td>'
        +'<td>'+qtyFmt+'</td>'
        +'<td class="hide-sm">'+usd(p.avgCost)+'</td>'
        +'<td class="price-cell" data-sym="'+p.symbol+'">'+usd(p.currentPrice)+'</td>'
        +'<td>'+usd(p.mktVal)+'</td>'
        +'<td class="hide-sm">'+usd(p.costBasis)+'</td>'
        +'<td class="chg-cell" data-sym="'+p.symbol+'">'+span(gc(p.dayPnl), usd(p.dayPnl))+'<div class="sub-text">'+pct(p.dayPct)+'</div></td>'
        +'<td>'
          +'<div class="bar-wrap">'
            +'<span>'+span(gc(p.totalPnl), usd(p.totalPnl))+'</span>'
            +'<div class="mini-bar '+barCls+'" style="width:'+barW+'px"></div>'
          +'</div>'
        +'</td>'
        +'<td>'+span(gc(p.totalPct), pct(p.totalPct))+'</td>'
        +'<td>'+(p.weight > 12
          ? '<span style="color:var(--red);font-weight:700">'+num(p.weight,1)+'%</span>'
          : p.weight > 8
            ? '<span style="color:#fbbf24;font-weight:600">'+num(p.weight,1)+'%</span>'
            : num(p.weight,1)+'%')+'</td>'
        +'<td><button class="sell-pos-btn" data-sym="'+p.symbol+'" style="background:none;border:1px solid rgba(239,68,68,0.3);color:var(--red);border-radius:5px;padding:3px 9px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;transition:background .15s,border-color .15s;">Sell</button></td>'
        +'</tr>';
    }).join('') : '<tr class="empty-row"><td colspan="10">No positions found.</td></tr>';

    document.querySelectorAll('thead th[data-col]').forEach(th => {
      th.classList.remove('sort-asc','sort-desc');
      if (th.dataset.col === sortCol) th.classList.add(sortDir==='asc'?'sort-asc':'sort-desc');
    });
  }

  document.querySelectorAll('thead th[data-col]').forEach(th => {
    th.addEventListener('click', () => {
      if (sortCol === th.dataset.col) sortDir = sortDir==='asc'?'desc':'asc';
      else { sortCol = th.dataset.col; sortDir = 'desc'; }
      renderTable();
    });
  });

  function _marketStatusNY() {
    // Compute market open/closed purely from New York local time — no API needed.
    // Regular session: Mon–Fri 09:30–16:00 ET. Does not account for holidays.
    const nyStr = new Date().toLocaleString('en-US', { timeZone: 'America/New_York' });
    const ny = new Date(nyStr);
    const day = ny.getDay();            // 0=Sun … 6=Sat
    const h = ny.getHours();
    const m = ny.getMinutes();
    const mins = h * 60 + m;
    const isWeekday = day >= 1 && day <= 5;
    const inSession = mins >= 9 * 60 + 30 && mins < 16 * 60;
    const open = isWeekday && inSession;

    $('mDot').className = 'dot ' + (open ? 'open' : 'closed');

    if (!isWeekday) {
      $('mStatus').textContent = 'Market Closed (weekend)';
    } else if (mins < 9 * 60 + 30) {
      const waitMin = (9 * 60 + 30) - mins;
      $('mStatus').textContent = 'Pre-Market · opens in ' + waitMin + 'm';
    } else if (mins >= 16 * 60) {
      $('mStatus').textContent = 'Market Closed · after hours';
    } else {
      // In session — show time remaining
      const closeMin = 16 * 60 - mins;
      $('mStatus').textContent = 'Market Open · closes in ' + closeMin + 'm';
    }
  }

  function loadMarket() {
    _marketStatusNY();
  }

  function showPage(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item[data-page]').forEach(n => n.classList.remove('active'));
    const pg = $('page-' + page);
    if (pg) pg.classList.add('active');
    const ni = document.querySelector('.nav-item[data-page="' + page + '"]');
    if (ni) ni.classList.add('active');
    const titles = {
      buyscan: {
        title: 'Opportunity Queue',
        pill: 'Live approvals',
        subtitle: 'Review fresh ideas, run scans on demand, and move to live orders only after preview plus confirmation.',
      },
      overview: {
        title: 'Morning Briefing',
        pill: 'Market context',
        subtitle: 'Start here for the AI brief and the most relevant news affecting names you already hold.',
      },
      portfolio: {
        title: 'Holdings',
        pill: 'Live positions',
        subtitle: 'Monitor exposure, returns, and position-level detail without leaving the main workspace.',
      },
      alerts: {
        title: 'Risk Monitor',
        pill: 'Scan history',
        subtitle: 'Track open issues, acknowledge what you have reviewed, and keep the portfolio watchlist clean.',
      },
      performance: {
        title: 'Performance',
        pill: 'History + catalysts',
        subtitle: 'Compare account progress over time, sync historical data, and keep upcoming earnings in view.',
      },
      journal: {
        title: 'Trade Journal',
        pill: 'Process review',
        subtitle: 'Reconstruct completed trades so you can review execution quality, not just the outcome.',
      },
      advisor: {
        title: 'Ask Advisor',
        pill: 'Live chat',
        subtitle: 'Use the advisor for position analysis, scenario planning, and portfolio questions grounded in live data.',
      },
    };
    const meta = titles[page] || { title: page, pill: 'Workspace', subtitle: '' };
    const tb = $('topbarTitle');
    const tp = $('topbarPill');
    const ts = $('topbarSubtitle');
    if (tb) tb.textContent = meta.title;
    if (tp) tp.textContent = meta.pill;
    if (ts) ts.textContent = meta.subtitle;
    // Lazy-load page data on first visit
    if (page === 'overview' && !_pagesLoaded.overview) {
      _pagesLoaded.overview = true;
      loadBriefing();
    }
    if (page === 'performance' && !_pagesLoaded.performance) {
      _pagesLoaded.performance = true;
      loadPerformance();
      loadEarnings();
    }
    if (page === 'journal' && !_pagesLoaded.journal) {
      _pagesLoaded.journal = true;
      loadJournal();
    }
  }
  const _pagesLoaded = {};

  if (window.lucide) lucide.createIcons();
  loadDashboard();
  loadMarket();
  loadAgentAlerts();
  // Full refresh every 60 s — live prices arrive faster via SSE below
  setInterval(loadDashboard, 60000);
  setInterval(loadMarket, 30000);
  setInterval(loadAgentAlerts, 120000);  // refresh alerts every 2 min

  // ── Live quote streaming (SSE) ─────────────────────────────────
  (async () => {
    // Ask the server to connect to Schwab's WebSocket; no-op if already running
    try { await fetch('/api/v1/schwab/stream/start', { method: 'POST' }); } catch {}
  })();

  const _lastPrice = {};   // sym → last known price for flash direction
  let _quoteSource = null;

  function startQuoteStream() {
    if (_quoteSource) return;
    _quoteSource = new EventSource('/api/v1/schwab/stream');

    _quoteSource.onmessage = e => {
      let quotes;
      try { quotes = JSON.parse(e.data); } catch { return; }
      Object.entries(quotes).forEach(([sym, q]) => {
        const last = q.last;
        if (last == null) return;

        const prev = _lastPrice[sym];
        const dir  = prev == null ? null : last > prev ? 'up' : last < prev ? 'down' : null;
        _lastPrice[sym] = last;

        // Update price cell
        const pc = document.querySelector('.price-cell[data-sym="' + sym + '"]');
        if (pc) {
          pc.textContent = '$' + last.toFixed(2);
          if (dir) {
            pc.classList.remove('flash-up', 'flash-down');
            void pc.offsetWidth;  // force reflow so animation restarts
            pc.classList.add('flash-' + dir);
          }
        }

        // Update day-change cell using netChange/netPctChange from stream
        const netChg = q.netChange;
        const netPct = q.netPctChange;
        if (netChg != null) {
          const pos = positions.find(p => p.symbol === sym);
          const qty = pos ? Math.abs(pos.qty) : 1;
          const dayPnl = netChg * qty;               // total $ P&L for the day

          const cc = document.querySelector('.chg-cell[data-sym="' + sym + '"]');
          if (cc) {
            const col = netChg >= 0 ? 'var(--green)' : 'var(--red)';
            const sign = netChg >= 0 ? '+' : '';
            const pctStr = netPct != null ? sign + netPct.toFixed(2) + '%' : '';
            cc.innerHTML = '<span style="color:' + col + '">' + sign + '$' + dayPnl.toFixed(2) + '</span>'
              + (pctStr ? '<div class="sub-text">' + pctStr + '</div>' : '');
          }
        }
      });
    };

    _quoteSource.onerror = () => {
      // Browser auto-reconnects EventSource; nothing to do
    };
  }

  // Start SSE after a short delay so the server-side WS has time to connect
  setTimeout(startQuoteStream, 3000);

  // ── Agent alerts ──────────────────────────────────────────────
  const SEV_ICON = { HIGH: '!', MEDIUM: '–', LOW: '' };
  const SEV_CLASS = { HIGH: 'flag-high', MEDIUM: 'flag-medium', LOW: 'flag-low' };

  // ── Stat card drill-down modal ────────────────────────────────
  function closeStatModal() {
    $('statOverlay').classList.remove('open');
  }

  function openStatModal(type) {
    if (!positions || !positions.length) return;
    const overlay = $('statOverlay');
    const title = $('statTitle');
    const body = $('statBody');

    if (type === 'value') {
      title.textContent = 'Portfolio Breakdown';
      const sorted = [...positions].filter(p => p.mktVal > 0).sort((a,b) => b.mktVal - a.mktVal);
      const total = sorted.reduce((s,p) => s + p.mktVal, 0);
      body.innerHTML = '<div class="stat-section">By Position</div>'
        + sorted.map(p => {
          const pct = total > 0 ? (p.mktVal / total * 100).toFixed(1) : '0.0';
          const bar = `<div style="height:3px;background:var(--accent);border-radius:2px;width:${Math.min(pct,100)}%;margin-top:4px;opacity:.6"></div>`;
          return `<div class="stat-row">
            <span class="stat-row-sym">${p.symbol}</span>
            <span class="stat-row-name">${pct}% of portfolio</span>
            <span class="stat-row-val">${usd(p.mktVal)}</span>
          </div>${bar}`;
        }).join('');

    } else if (type === 'day') {
      title.textContent = "Today's P&L Breakdown";
      const sorted = [...positions].sort((a,b) => b.dayPnl - a.dayPnl);
      const total = positions.reduce((s,p) => s + p.dayPnl, 0);
      const winners = sorted.filter(p => p.dayPnl > 0);
      const losers  = sorted.filter(p => p.dayPnl < 0);
      const flat    = sorted.filter(p => p.dayPnl === 0);
      const renderGroup = (label, list) => list.length
        ? `<div class="stat-section">${label}</div>` + list.map(p =>
            `<div class="stat-row">
              <span class="stat-row-sym">${p.symbol}</span>
              <span class="stat-row-name">${p.dayPct >= 0 ? '+' : ''}${p.dayPct.toFixed(2)}%</span>
              <span class="stat-row-val" style="color:${p.dayPnl>=0?'var(--green)':'var(--red)'}">${p.dayPnl>=0?'+':''}${usd(p.dayPnl)}</span>
            </div>`).join('')
        : '';
      body.innerHTML = `<div style="margin-bottom:14px">
          <div class="stat-big" style="color:${total>=0?'var(--green)':'var(--red)'}">${total>=0?'+':''}${usd(total)}</div>
          <div class="stat-sub">Total day P&L across ${positions.length} positions</div>
        </div>`
        + renderGroup('Winners', winners)
        + renderGroup('Losers', losers)
        + renderGroup('Unchanged', flat);

    } else if (type === 'return') {
      title.textContent = 'Total Return Breakdown';
      const sorted = [...positions].sort((a,b) => b.totalPnl - a.totalPnl);
      const totalPnl = positions.reduce((s,p) => s + p.totalPnl, 0);
      const totalCost = positions.reduce((s,p) => s + p.costBasis, 0);
      const totalPct = totalCost > 0 ? (totalPnl / totalCost * 100) : 0;
      const winners = sorted.filter(p => p.totalPnl > 0);
      const losers  = sorted.filter(p => p.totalPnl < 0);
      const renderGroup = (label, list) => list.length
        ? `<div class="stat-section">${label}</div>` + list.map(p =>
            `<div class="stat-row">
              <span class="stat-row-sym">${p.symbol}</span>
              <span class="stat-row-name">${p.totalPct>=0?'+':''}${p.totalPct.toFixed(1)}%</span>
              <span class="stat-row-val" style="color:${p.totalPnl>=0?'var(--green)':'var(--red)'}">${p.totalPnl>=0?'+':''}${usd(p.totalPnl)}</span>
            </div>`).join('')
        : '';
      body.innerHTML = `<div style="margin-bottom:14px">
          <div class="stat-big" style="color:${totalPnl>=0?'var(--green)':'var(--red)'}">${totalPnl>=0?'+':''}${usd(totalPnl)}</div>
          <div class="stat-sub">${totalPct>=0?'+':''}${totalPct.toFixed(2)}% all-time return on ${usd(totalCost)} invested</div>
        </div>`
        + renderGroup('Gainers', winners)
        + renderGroup('Losers', losers)
        + `<div style="margin-top:16px;text-align:center">
            <button class="btn-sm" onclick="closeStatModal();showPage('performance')">View Full Performance Chart</button>
           </div>`;

    } else if (type === 'cash') {
      title.textContent = 'Cash & Buying Power';
      const invested = positions.reduce((s,p) => s + p.mktVal, 0);
      const cash = parseFloat($('cCash').textContent.replace(/[$,]/g,'')) || 0;
      const total = invested + cash;
      const cashPct = total > 0 ? (cash / total * 100).toFixed(1) : '0';
      body.innerHTML = `
        <div class="stat-row"><span class="stat-row-sym">Cash</span><span class="stat-row-name">Available to trade</span><span class="stat-row-val">${usd(cash)}</span></div>
        <div class="stat-row"><span class="stat-row-sym">Invested</span><span class="stat-row-name">Across ${positions.length} positions</span><span class="stat-row-val">${usd(invested)}</span></div>
        <div class="stat-row"><span class="stat-row-sym">Cash %</span><span class="stat-row-name">Of total portfolio</span><span class="stat-row-val">${cashPct}%</span></div>
        <div style="margin-top:16px;padding:12px;background:rgba(255,255,255,.03);border-radius:8px;font-size:12px;color:var(--muted)">
          Cash is held in your Schwab account and earns SPAXX money market rates automatically.
        </div>`;

    } else if (type === 'health') {
      title.textContent = 'Portfolio Health Score';
      const score = parseInt($('healthScore').textContent) || 0;
      const conc = positions.length > 0 ? Math.max(...positions.map(p => p.weight)).toFixed(1) : 0;
      const losers = positions.filter(p => p.totalPct < -8).length;
      const bigGainers = positions.filter(p => p.totalPct > 30).length;
      const color = score >= 80 ? 'var(--green)' : score >= 60 ? '#fbbf24' : 'var(--red)';
      body.innerHTML = `
        <div style="text-align:center;margin-bottom:20px">
          <div class="stat-big" style="color:${color};font-size:48px">${score}</div>
          <div class="stat-sub">${$('healthLabel').textContent}</div>
        </div>
        <div class="stat-section">Score Factors</div>
        <div class="stat-row"><span class="stat-row-sym">Positions</span><span class="stat-row-name">Diversification</span><span class="stat-row-val">${positions.length} held</span></div>
        <div class="stat-row"><span class="stat-row-sym">Concentration</span><span class="stat-row-name">Largest single position</span><span class="stat-row-val">${conc}%</span></div>
        <div class="stat-row"><span class="stat-row-sym">Losers</span><span class="stat-row-name">Down more than 8%</span><span class="stat-row-val" style="color:${losers>0?'var(--red)':'var(--green)'}">${losers}</span></div>
        <div class="stat-row"><span class="stat-row-sym">Big gains</span><span class="stat-row-name">Up more than 30%</span><span class="stat-row-val" style="color:var(--green)">${bigGainers}</span></div>
        <div style="margin-top:16px;padding:12px;background:rgba(255,255,255,.03);border-radius:8px;font-size:12px;color:var(--muted)">
          Health score reflects concentration risk, drawdown depth, and position balance. 80+ is strong, 60–79 is moderate, below 60 needs attention.
        </div>`;
    }

    overlay.classList.add('open');
  }

  // Close modal on Escape key
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeStatModal(); });

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function toggleThesis(btn) {
    const t = btn.previousElementSibling;
    if (t.style.webkitLineClamp === 'unset') {
      t.style.webkitLineClamp = '3';
      btn.textContent = 'Show more';
    } else {
      t.style.webkitLineClamp = 'unset';
      btn.textContent = 'Show less';
    }
  }

  function renderEmptyState(title, body, actionLabel, actionJs, tone) {
    const toneColor = tone === 'success'
      ? ' style="color:var(--green);"'
      : tone === 'danger'
        ? ' style="color:var(--red);"'
        : '';
    const actionHtml = (actionLabel && actionJs)
      ? '<div class="empty-actions">'
        + '<button class="empty-btn empty-btn-primary" onclick="' + actionJs + '">'
        + _esc(actionLabel)
        + '</button></div>'
      : '';
    return '<div class="empty-state">'
      + '<div class="empty-title"' + toneColor + '>' + _esc(title) + '</div>'
      + '<div class="empty-body">' + _esc(body) + '</div>'
      + actionHtml
      + '</div>';
  }

  function _renderAlertCard(a) {
    const ts = new Date(a.timestamp).toLocaleString('en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
    const isPending  = a.status === 'pending';
    const isBuyScan  = a.alert_type === 'BUY_SCAN';
    const isSellScan = a.alert_type === 'SELL_SCAN';
    const isDismissed = (a.status === 'denied' || a.status === 'cancelled');

    // ── Content (portfolio scans only) ───────────────────────────
    let contentHtml = '';
    if (!isBuyScan && !isSellScan) {
      const ca = a.claude_analysis;
      if (ca && typeof ca === 'object' && (ca.items || []).length) {
        // Claude analysis: verdict + action items
        const urgClass = { NOW:'urg-now', WATCH:'urg-watch', FYI:'urg-fyi' };
        if (ca.verdict) contentHtml += '<div class="scan-verdict">' + _esc(ca.verdict) + '</div>';
        contentHtml += (ca.items || []).map(it =>
          '<div class="scan-item">'
          + '<span class="' + (urgClass[it.urgency] || 'urg-fyi') + '">' + _esc(it.urgency || 'FYI') + '</span>'
          + '<div class="scan-item-body" style="flex:1;">'
          + '<div class="scan-item-title">' + _esc(it.symbol) + ' &middot; ' + _esc(it.title) + '</div>'
          + (it.detail ? '<div class="scan-item-detail">' + _esc(it.detail) + '</div>' : '')
          + '</div>'
          + (it.symbol && it.symbol !== '?' ? '<button class="btn-mute" data-sym="' + _esc(it.symbol) + '" title="Mute alerts for this symbol for 7 days">Mute 7d</button>' : '')
          + '</div>'
        ).join('');
      } else if ((a.flags || []).length) {
        // Fallback: group raw flags by symbol, deduplicated
        const grouped = {};
        (a.flags || []).forEach(f => {
          const k = f.symbol || '?';
          if (!grouped[k]) grouped[k] = [];
          const desc = f.description || f.type || '';
          if (!grouped[k].includes(desc)) grouped[k].push(desc);
        });
        contentHtml += '<div class="scan-flags">'
          + Object.entries(grouped).map(([sym, descs]) =>
              '<div class="scan-flag-row">'
              + '<span class="scan-flag-sym">' + _esc(sym) + '</span>'
              + '<span class="scan-flag-text">' + descs.map(_esc).join(' &middot; ') + '</span>'
              + '</div>'
            ).join('')
          + '</div>';
      }
    }

    // ── Proposals ────────────────────────────────────────────────
    const pendingProps = (a.proposals || []).filter(p => p.status === 'pending');
    const doneProps    = (a.proposals || []).filter(p => p.status !== 'pending');
    let propsHtml = '';

    if (pendingProps.length) {
      const budgetNum = a.budget ? parseFloat(a.budget) : null;
      const budgetTag = budgetNum ? '<span class="ideas-budget-tag">Budget $' + budgetNum.toLocaleString(undefined,{maximumFractionDigits:0}) + '</span>' : '';
      const sectionLabel = isBuyScan ? 'Trade Ideas' : 'Suggested Actions';
      propsHtml = '<div class="props-section">'
        + '<div class="ideas-section-head">'
        + '<span class="ideas-section-label">' + sectionLabel + '</span>'
        + budgetTag
        + '</div>'
        + pendingProps.map(p => {
            proposalMap[p.id] = p;
            const isBuy = p.action === 'BUY';
            const accentColor  = isBuy ? '#3fb950' : '#f85149';
            const accentBg     = isBuy ? 'rgba(63,185,80,0.13)' : 'rgba(248,81,73,0.13)';
            const qty   = parseInt(p.quantity) || p.quantity;
            const price = p.limit_price ? parseFloat(p.limit_price) : null;
            const total = (price && p.quantity) ? price * parseFloat(p.quantity) : null;
            const priceDisp = price ? '$' + price.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}) : 'Market';
            const totalDisp = total ? '$' + total.toLocaleString(undefined,{maximumFractionDigits:0}) : '—';
            const orderType = (p.order_type || 'LIMIT').toUpperCase();
            const urgCfg = {
              HIGH:   {color:'#f87171', bg:'rgba(248,113,113,0.10)', label:'HIGH CONVICTION'},
              MEDIUM: {color:'#fbbf24', bg:'rgba(251,191,36,0.08)',  label:'MEDIUM'},
              LOW:    {color:'#6ee7b7', bg:'rgba(110,231,183,0.08)', label:'WATCHLIST'},
            }[p.urgency] || {color:'var(--muted)', bg:'var(--surface2)', label:p.urgency||'IDEA'};
            const thesisId = 'thesis-' + p.id.replace(/[^a-z0-9]/gi,'_');
            const accentBar = isBuy ? 'var(--green)' : 'var(--red)';
            const costLabel = isBuy ? 'Est. Cost' : 'Est. Proceeds';
            return '<div class="idea-card">'
              + '<div class="idea-card-inner">'
              +   '<div class="idea-card-accent" style="background:'+accentBar+';"></div>'
              +   '<div class="idea-card-main">'
              +     '<div class="idea-card-top">'
              +       '<div class="idea-card-topleft">'
              +         '<div class="idea-pills">'
              +           '<span class="idea-action-pill" style="background:'+accentBg+';color:'+accentColor+';">'+_esc(p.action)+'</span>'
              +           (urgCfg.label ? '<span class="idea-urgency-pill" style="background:'+urgCfg.bg+';color:'+urgCfg.color+';">'+urgCfg.label+'</span>' : '')
              +           ((() => { const lp = (typeof positions!=='undefined'?positions:[]).find(x=>x.symbol===p.symbol); return lp ? '<span class="idea-urgency-pill" style="background:rgba(37,99,235,.12);color:#60a5fa;">You own '+Math.floor(lp.qty)+'sh</span>' : ''; })())
              +         '</div>'
              +         '<div class="idea-sym-block">'
              +           '<div class="idea-sym">'+_esc(p.symbol)+'</div>'
              +           '<div class="idea-sym-sub">'+orderType+' &middot; '+qty+' shares</div>'
              +         '</div>'
              +       '</div>'
              +       '<div class="idea-card-topright">'
              +         '<div class="idea-cost-label">'+costLabel+'</div>'
              +         '<div class="idea-cost-val">'+totalDisp+'</div>'
              +       '</div>'
              +     '</div>'
              +     '<div class="idea-div"></div>'
              +     '<div class="idea-metrics">'
              +       '<div class="idea-metric"><div class="idea-metric-label">Shares</div><div class="idea-metric-val">'+qty+'</div></div>'
              +       '<div class="idea-metric"><div class="idea-metric-label">'+orderType+' Price</div><div class="idea-metric-val">'+priceDisp+'</div></div>'
              +       '<div class="idea-metric"><div class="idea-metric-label">Total</div><div class="idea-metric-val">'+totalDisp+'</div></div>'
              +     '</div>'
              +     (p.reasoning ? '<div class="idea-thesis">'
              +       '<div class="idea-thesis-label">AI Thesis</div>'
              +       '<div class="idea-thesis-text" id="'+thesisId+'">'+_esc(p.reasoning)+'</div>'
              +       '<button class="idea-thesis-toggle" onclick="toggleThesis(this)">Show more</button>'
              +     '</div>' : '')
              +     '<div class="idea-btns">'
              +       '<button class="idea-btn-place" data-pid="'+p.id+'" data-action="execute">Place Order</button>'
              +       '<button class="idea-btn-pass"  data-pid="'+p.id+'" data-action="skip">Pass</button>'
              +     '</div>'
              +   '</div>'
              + '</div>'
              + '</div>';
          }).join('')
        + '</div>';
    }
    if (doneProps.length) {
      propsHtml += '<div class="props-done">'
        + doneProps.map(p => {
            proposalMap[p.id] = p;   // register so "Review Again" can find it
            const isExec = p.status === 'executed';
            const cardCls = isExec ? 'done-card executed' : 'done-card cancelled';
            const badgeText = isExec ? 'EXECUTED' : 'ARCHIVED';
            const qty   = parseInt(p.quantity) || p.quantity;
            const price = p.limit_price ? parseFloat(p.limit_price) : null;
            const total = (price && p.quantity) ? price * parseFloat(p.quantity) : null;
            const priceStr = price ? '$' + price.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}) : 'market';
            const totalStr = total ? ' &middot; ~$' + total.toLocaleString(undefined,{maximumFractionDigits:0}) : '';
            const detail = isExec
              ? '<strong>' + qty + ' shares</strong> @ ' + priceStr + totalStr
              : qty + ' shares @ ' + priceStr + ' — not executed';
            const buyAnywayBtn = isExec ? '' : '<button class="btn-review-again" data-pid="' + p.id + '" data-action="execute">Review Again</button>';
            const quickSellBtn = (isExec && p.action === 'BUY') ? '<button class="sell-pos-btn" data-sym="' + _esc(p.symbol) + '" style="background:none;border:1px solid rgba(239,68,68,0.3);color:var(--red);border-radius:5px;padding:3px 9px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;margin-right:6px;">Sell</button>' : '';

            // Exit target progress bar for executed BUY proposals
            let exitBarHtml = '';
            if (isExec && p.action === 'BUY' && p.target_price && p.stop_price && p.limit_price) {
              const entry  = parseFloat(p.limit_price);
              const target = parseFloat(p.target_price);
              const stop   = parseFloat(p.stop_price);
              const range  = target - stop;
              // Try to get current price from live positions data
              const livePosArr = (typeof positions !== 'undefined' ? positions : []);
              const livePos = livePosArr.find(lp => lp.symbol === p.symbol);
              const cur = livePos ? (livePos.currentPrice || entry) : entry;
              const clampedCur = Math.max(stop * 0.97, Math.min(target * 1.03, cur));
              const fillPct = Math.max(0, Math.min(100, ((clampedCur - stop) / range) * 100));
              const cursorPct = fillPct;
              const fillColor = cur >= target ? '#3fb950' : cur <= stop ? '#f85149' : '#fbbf24';
              const stopFmt   = '$' + stop.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
              const tgtFmt    = '$' + target.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
              const curFmt    = '$' + cur.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
              exitBarHtml = '<div class="exit-target-bar">'
                + '<div class="exit-target-label">'
                + '<span>Stop ' + stopFmt + '</span>'
                + '<span style="color:var(--ink);font-weight:600;">Now ' + curFmt + '</span>'
                + '<span>Target ' + tgtFmt + '</span>'
                + '</div>'
                + '<div class="exit-track">'
                + '<div class="exit-fill" style="width:' + fillPct + '%;background:' + fillColor + ';"></div>'
                + '<div class="exit-cursor" style="left:' + cursorPct + '%;background:' + fillColor + ';"></div>'
                + '</div>'
                + '</div>';
            }

            return '<div class="' + cardCls + '">'
              + '<div class="done-card-status"></div>'
              + '<div class="done-card-body">'
              + '<span class="done-card-sym">' + _esc(p.symbol) + '</span>'
              + '<span class="done-card-detail">' + detail + '</span>'
              + quickSellBtn
              + buyAnywayBtn
              + '<span class="done-card-badge">' + badgeText + '</span>'
              + '</div>'
              + exitBarHtml
              + '</div>';
          }).join('')
        + '</div>';
    }

    // ── Dismiss button (risk scans with no proposals) ─────────────
    const actionsHtml = (isPending && !pendingProps.length && !isBuyScan && !isSellScan)
      ? '<div class="scan-actions"><button class="btn-dismiss" data-alert-id="' + a.id + '" data-action="deny">Mark Reviewed</button></div>'
      : '';

    // ── Card header ───────────────────────────────────────────────
    const labelColor = isBuyScan ? 'var(--green)' : isSellScan ? 'var(--red)' : 'var(--muted)';
    const labelText  = isBuyScan ? 'Opportunity Scan' : isSellScan ? 'Exit Scan' : 'Risk Scan';
    const reviewedDot = (!isPending && !isDismissed)
      ? ' <span style="color:var(--green);font-size:11px;">&#10003;</span>' : '';

    const cardStyle = isBuyScan ? 'border-left:3px solid var(--green);'
                    : isSellScan ? 'border-left:3px solid var(--red);' : '';
    const cardClass = 'alert-card' + (isDismissed ? ' is-dismissed' : '');

    return '<div class="' + cardClass + '" style="' + cardStyle + '">'
      + '<div class="alert-card-header">'
      + '<span style="font-size:10px;font-weight:700;color:' + labelColor + ';text-transform:uppercase;letter-spacing:.07em;">' + labelText + '</span>'
      + reviewedDot
      + '<span class="alert-time">' + ts + '</span>'
      + '</div>'
      + contentHtml
      + propsHtml
      + actionsHtml
      + '</div>';
  }

  async function loadAgentAlerts() {
    try {
      const [statusR, alertsR] = await Promise.all([
        fetch('/api/v1/agent/status'),
        fetch('/api/v1/agent/alerts?limit=20'),
      ]);
      if (!statusR.ok || !alertsR.ok) return;
      const agentSt = await statusR.json();
      const alerts = await alertsR.json();

      const el = $('agentStatus');
      if (el) el.textContent = 'Auto-scans every ' + agentSt.check_interval_minutes + ' minutes';

      // Split buy scan vs portfolio/sell alerts
      const buyScanAlerts = alerts.filter(a => a.alert_type === 'BUY_SCAN');
      const portAlerts    = alerts.filter(a => a.alert_type !== 'BUY_SCAN');

      // Pending counts
      const pendingBuy  = buyScanAlerts.filter(a => a.status === 'pending').reduce((s,a) => s + (a.proposals||[]).filter(p=>p.status==='pending').length, 0);
      const pendingPort = portAlerts.filter(a => a.status === 'pending').length;

      const scanBadgeEl = $('scanBadge');
      if (scanBadgeEl) {
        if (pendingBuy > 0) { scanBadgeEl.textContent = pendingBuy; scanBadgeEl.style.display = 'inline'; }
        else scanBadgeEl.style.display = 'none';
      }
      const alertBadgeEl = $('alertBadge');
      if (alertBadgeEl) {
        if (pendingPort > 0) { alertBadgeEl.textContent = pendingPort; alertBadgeEl.style.display = 'inline'; }
        else alertBadgeEl.style.display = 'none';
      }

      // Populate Buy Scan page
      const scanBodyEl = $('scanBody');
      if (scanBodyEl) {
        if (!buyScanAlerts.length) {
          scanBodyEl.innerHTML = renderEmptyState(
            'No opportunity scans yet',
            'Run the opportunity scan to have the agent research your watchlist and surface the highest-conviction ideas that fit your budget.',
            'Run opportunity scan',
            'runBuyScan()'
          );
        } else {
          const latest = buyScanAlerts[0];
          const prev   = buyScanAlerts.slice(1);
          let html = _renderAlertCard(latest);
          if (prev.length) {
            html += '<div id="prevScanWrap" style="display:none;">' + prev.map(_renderAlertCard).join('') + '</div>'
              + '<div style="padding:8px 18px 14px;text-align:center;">'
              + '<button onclick="var w=$(`prevScanWrap`);w.style.display=w.style.display===`none`?``:`none`;this.textContent=w.style.display===``?`\u25b2 Hide previous`:`\u25bc ' + prev.length + ' previous scan' + (prev.length>1?'s':'') + '`;"'
              + ' style="background:none;border:none;color:var(--muted);font-size:12px;cursor:pointer;">'
              + '\u25bc ' + prev.length + ' previous scan' + (prev.length>1?'s':'') + '</button></div>';
          }
          scanBodyEl.innerHTML = html;
        }
      }

      // Populate Alerts page
      const agentBodyEl = $('agentBody');
      if (agentBodyEl) {
        if (!portAlerts.length) {
          agentBodyEl.innerHTML = renderEmptyState(
            'No risk alerts right now',
            'Run a risk scan to refresh the monitor and look for new issues in the live portfolio.',
            'Run risk scan',
            'runAgentCheck()'
          );
        } else {
          const latest = portAlerts[0];
          const prev   = portAlerts.slice(1);
          let html = _renderAlertCard(latest);
          if (prev.length) {
            html += '<div id="prevScansWrap" style="display:none;">'
              + prev.map(_renderAlertCard).join('')
              + '</div>'
              + '<div style="padding:8px 18px 14px;text-align:center;">'
              + '<button onclick="var w=$(`prevScansWrap`);w.style.display=w.style.display===`none`?``:`none`;this.textContent=w.style.display===``?`\u25b2 Hide previous scans`:`\u25bc '
              + prev.length + ' previous scan' + (prev.length > 1 ? 's' : '') + '`;"'
              + ' style="background:none;border:none;color:var(--muted);font-size:12px;cursor:pointer;">'
              + '\u25bc ' + prev.length + ' previous scan' + (prev.length > 1 ? 's' : '')
              + '</button></div>';
          }
          agentBodyEl.innerHTML = html;
        }
      }
    } catch(_) {}
  }

  async function runAgentCheck() {
    const btn = $('runCheckBtn');
    btn.disabled = true;
    btn.textContent = 'Scanning...';
    try {
      const r = await fetch('/api/v1/agent/run-check', { method: 'POST' });
      const d = await r.json();
      if (d.status === 'no_flags') {
        $('agentBody').innerHTML = renderEmptyState(
          'Portfolio looks clean',
          'The latest risk scan did not find any new issues that need review.',
          null,
          null,
          'success'
        );
        setTimeout(loadAgentAlerts, 1800);
      } else {
        await loadAgentAlerts();
      }
    } catch(e) {
      $('agentBody').innerHTML = renderEmptyState(
        'Risk scan failed',
        e.message,
        'Try again',
        'runAgentCheck()',
        'danger'
      );
    } finally {
      btn.disabled = false;
      btn.textContent = 'Run Risk Scan';
    }
  }

  async function runBuyScan() {
    const btn = $('buyCheckBtn');
    btn.disabled = true;
    btn.textContent = 'Scanning...';
    const scanBodyEl = $('scanBody');
    if (scanBodyEl) {
      scanBodyEl.innerHTML = renderEmptyState(
        'Scanning for new ideas',
        'The agent is researching the watchlist now. Expect this to take about 30 to 60 seconds.',
        null,
        null
      );
    }
    try {
      const r = await fetch('/api/v1/agent/run-buy-scan', { method: 'POST' });
      const d = await r.json();
      if (d.status === 'no_candidates') {
        if (scanBodyEl) {
          scanBodyEl.innerHTML = renderEmptyState(
            'No high-conviction ideas right now',
            'Nothing in the watchlist cleared the current budget and confidence filters on this pass.',
            'Run again later',
            'runBuyScan()'
          );
        }
        setTimeout(loadAgentAlerts, 1800);
      } else {
        showPage('buyscan');
        await loadAgentAlerts();
      }
    } catch(e) {
      if (scanBodyEl) {
        scanBodyEl.innerHTML = renderEmptyState(
          'Opportunity scan failed',
          e.message,
          'Try again',
          'runBuyScan()',
          'danger'
        );
      }
    } finally {
      btn.disabled = false;
      btn.textContent = 'Run Opportunity Scan';
    }
  }

  async function runSellScan() {
    const btn = $('runSellScanBtn');
    btn.disabled = true;
    btn.textContent = 'Scanning...';
    try {
      const r = await fetch('/api/v1/agent/run-sell-scan', { method: 'POST' });
      const d = await r.json();
      if (d.status === 'no_candidates') {
        btn.textContent = 'No exits needed';
        setTimeout(() => { btn.textContent = 'Run Sell Scan'; }, 4000);
      } else {
        await loadAgentAlerts();
        showPage('agent');
      }
    } catch(e) {
      btn.textContent = 'Scan failed';
      setTimeout(() => { btn.textContent = 'Run Sell Scan'; }, 3000);
    } finally {
      btn.disabled = false;
    }
  }

  // ── Insider / Congressional Feed ───────────────────────────────────────────

  let _insiderData = [];

  async function loadInsiders() {
    const body = $('insidersBody');
    body.innerHTML = '<div class="empty-state">Loading insider data...</div>';
    try {
      // Use held positions only — much faster than scanning the full watchlist
      const syms = positions.map(p => p.symbol).filter(Boolean).join(',');
      const url = syms ? '/api/v1/agent/insider-feed?symbols=' + encodeURIComponent(syms) : '/api/v1/agent/insider-feed';
      const r = await fetch(url);
      const d = await r.json();
      _insiderData = d.trades || [];
      let html = '';
      if (!d.congressional_enabled) {
        html = '<div style="background:rgba(37,99,235,.08);border:1px solid rgba(37,99,235,.25);border-radius:6px;padding:12px 16px;margin-bottom:14px;font-size:13px;">'
          + '<strong style="color:#60a5fa;">Congressional trading data not enabled.</strong> '
          + 'Get a free API key at <strong>quiverquant.com</strong>, then paste it in '
          + '<a href="/customize" style="color:#60a5fa;text-decoration:underline;">Settings</a> under Connections &rarr; Quiver Quant API Key. '
          + 'This unlocks Pelosi, all House &amp; Senate member trades.'
          + '</div>';
      }
      const container = document.createElement('div');
      container.innerHTML = html;
      body.innerHTML = html;
      renderInsiders(_insiderData);
    } catch(e) {
      body.innerHTML = '<div class="empty-state">Failed to load insider data.</div>';
    }
  }

  function filterInsiders() {
    const f = document.getElementById('insiderFilter').value;
    let trades = _insiderData;
    if (f === 'buy') trades = trades.filter(t => t.type === 'buy');
    else if (f === 'sell') trades = trades.filter(t => t.type === 'sell');
    else if (f === 'congressional') trades = trades.filter(t => t.source === 'congressional');
    else if (f === 'corporate') trades = trades.filter(t => t.source === 'corporate');
    renderInsiders(trades);
  }

  function renderInsiders(trades) {
    const body = $('insidersBody');
    // Remove any previous table but keep setup banner if present
    const existing = body.querySelector('table, .empty-state:last-child');
    if (existing) existing.remove();
    if (!trades.length) {
      body.insertAdjacentHTML('beforeend', '<div class="empty-state">No trades found for current filter.</div>');
      return;
    }
    const rows = trades.map(function(t) {
      const isBuy = t.type === 'buy';
      const typeColor = isBuy ? 'var(--green)' : 'var(--red)';
      const typeLabel = isBuy ? 'BUY' : 'SELL';
      const sourceBadge = t.source === 'congressional'
        ? '<span style="font-size:10px;padding:1px 5px;background:rgba(139,92,246,.15);color:#a78bfa;border-radius:3px;">'
          + (t.chamber === 'senate' ? 'SENATE' : 'HOUSE') + (t.party ? ' &middot; ' + t.party : '') + '</span>'
        : '<span style="font-size:10px;padding:1px 5px;background:rgba(37,99,235,.12);color:#60a5fa;border-radius:3px;">INSIDER</span>';
      const valueStr = t.source === 'congressional'
        ? (t.amount_range || '')
        : (t.value ? '$' + t.value.toLocaleString() : (t.shares ? t.shares.toLocaleString() + ' sh' : ''));
      return '<tr>'
        + '<td style="padding:8px 10px;font-weight:600;">' + t.symbol + '</td>'
        + '<td style="padding:8px 10px;color:' + typeColor + ';font-weight:600;">' + typeLabel + '</td>'
        + '<td style="padding:8px 10px;">' + t.name + '</td>'
        + '<td style="padding:8px 10px;">' + t.title + ' ' + sourceBadge + '</td>'
        + '<td style="padding:8px 10px;color:var(--text-muted);">' + valueStr + '</td>'
        + '<td style="padding:8px 10px;color:var(--text-muted);">' + t.date + '</td>'
        + '</tr>';
    }).join('');
    body.insertAdjacentHTML('beforeend', '<div style="overflow-x:auto;">'
      + '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
      + '<thead><tr style="border-bottom:1px solid var(--border);color:var(--text-muted);font-size:11px;text-transform:uppercase;">'
      + '<th style="padding:6px 10px;text-align:left;">Symbol</th>'
      + '<th style="padding:6px 10px;text-align:left;">Type</th>'
      + '<th style="padding:6px 10px;text-align:left;">Name</th>'
      + '<th style="padding:6px 10px;text-align:left;">Role</th>'
      + '<th style="padding:6px 10px;text-align:left;">Amount</th>'
      + '<th style="padding:6px 10px;text-align:left;">Date</th>'
      + '</tr></thead>'
      + '<tbody>' + rows + '</tbody>'
      + '</table></div>');
  }

  // ── Thesis Tracker ─────────────────────────────────────────────────────────

  const _STATUS_COLOR = { INTACT: 'var(--green)', WEAKENING: 'var(--amber)', BROKEN: 'var(--red)' };
  const _ACTION_COLOR = { HOLD: 'var(--green)', TRIM: 'var(--amber)', EXIT: 'var(--red)' };

  async function loadThesis() {
    const body = $('thesisBody');
    body.innerHTML = '<div class="empty-state">Loading...</div>';
    try {
      const r = await fetch('/api/v1/agent/thesis');
      const d = await r.json();
      const theses = d.theses || [];
      if (!theses.length) {
        body.innerHTML = '<div class="empty-state">No thesis entries yet. Execute a buy proposal and run a check to start tracking.</div>';
        const badge = $('thesisBadge');
        if (badge) badge.style.display = 'none';
        return;
      }
      const broken = theses.filter(t => t.status === 'BROKEN' || t.status === 'WEAKENING').length;
      const badge = $('thesisBadge');
      if (badge) { badge.textContent = broken || ''; badge.style.display = broken ? '' : 'none'; }
      body.innerHTML = theses.map(function(t) {
        const sc = _STATUS_COLOR[t.status] || 'var(--text-muted)';
        const ac = _ACTION_COLOR[t.action] || 'var(--text-muted)';
        const lastCheck = (t.history || []).slice(-1)[0];
        const lastPrice = lastCheck ? lastCheck.price_at_check : t.entry_price;
        const pnl = t.entry_price ? (((lastPrice / t.entry_price) - 1) * 100).toFixed(1) : null;
        const checked = t.last_checked ? new Date(t.last_checked).toLocaleDateString() : 'Never';
        const thesis = (t.original_thesis || '').slice(0, 140) + ((t.original_thesis || '').length > 140 ? '...' : '');
        const pnlHtml = pnl !== null
          ? '<div style="font-size:12px;color:var(--text-muted);margin-bottom:4px;">Entry $' + (t.entry_price || 0).toFixed(2) + ' &middot; ' + (pnl >= 0 ? '+' : '') + pnl + '% &middot; Last checked ' + checked + '</div>'
          : '';
        const notesHtml = (t.notes && t.notes !== 'Not yet reviewed.')
          ? '<div style="font-size:13px;color:var(--text-primary);">' + t.notes + '</div>'
          : '';
        const confHtml = t.confidence
          ? '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Confidence: ' + t.confidence + '/10</div>'
          : '';
        return '<div class="alert-card" style="border-left:3px solid ' + sc + ';margin-bottom:10px;">'
          + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
          + '<span style="font-weight:700;font-size:15px;">' + t.symbol + '</span>'
          + '<div style="display:flex;gap:8px;align-items:center;">'
          + '<span style="color:' + sc + ';font-size:12px;font-weight:600;">' + t.status + '</span>'
          + '<span style="color:' + ac + ';font-size:12px;padding:2px 7px;border:1px solid ' + ac + ';border-radius:4px;">' + t.action + '</span>'
          + '</div></div>'
          + pnlHtml
          + '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:6px;font-style:italic;">&ldquo;' + thesis + '&rdquo;</div>'
          + notesHtml + confHtml
          + '</div>';
      }).join('');
    } catch(e) {
      body.innerHTML = '<div class="empty-state">Failed to load thesis data.</div>';
    }
  }

  async function runThesisCheck() {
    const btn = $('thesisCheckBtn');
    btn.disabled = true;
    btn.textContent = 'Checking...';
    try {
      const r = await fetch('/api/v1/agent/run-thesis-check', { method: 'POST' });
      const d = await r.json();
      await loadThesis();
      btn.textContent = 'Done (' + (d.checked || 0) + ' checked)';
      setTimeout(() => { btn.textContent = 'Run Check'; }, 4000);
    } catch(e) {
      btn.textContent = 'Check failed';
      setTimeout(() => { btn.textContent = 'Run Check'; }, 3000);
    } finally {
      btn.disabled = false;
    }
  }

  // ── Market Overview ─────────────────────────────────────────────────────────
  async function loadMacro() {
    const body = $('macroBody');
    body.innerHTML = '<div class="empty-state">Loading market data... (fetches ~11 tickers via yfinance)</div>';
    try {
      const r = await fetch('/api/v1/agent/macro');
      if (!r.ok) throw new Error(r.statusText);
      const d = await r.json();
      renderMacro(d);
      const upd = $('macroUpdated');
      if (upd) upd.textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch(e) {
      body.innerHTML = '<div class="empty-state">Failed to load market data: ' + e.message + '</div>';
    }
  }

  function renderMacro(d) {
    const body = $('macroBody');
    const REGIME_COLOR = { BULLISH: 'var(--green)', NEUTRAL: 'var(--amber)', BEARISH: 'var(--red)' };
    const regimeColor = REGIME_COLOR[d.regime] || 'var(--muted)';

    // VIX color
    const vix = d.vix || 0;
    const vixColor = vix < 15 ? 'var(--green)' : vix < 20 ? 'var(--accent)' : vix < 30 ? 'var(--amber)' : 'var(--red)';

    let html = '<div style="padding:16px;">';

    // Regime banner
    html += '<div style="background:var(--surface);border:1px solid ' + regimeColor + ';border-radius:8px;padding:14px 18px;margin-bottom:16px;display:flex;align-items:center;gap:16px;">';
    html += '<span style="font-size:18px;font-weight:700;color:' + regimeColor + ';">' + (d.regime || 'UNKNOWN') + '</span>';
    html += '<span style="color:var(--fg2);font-size:13px;">' + (d.interpretation || '') + '</span>';
    html += '</div>';

    // Key indices row: VIX, SPY, QQQ
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:18px;">';

    // VIX card
    html += '<div style="background:var(--surface);border-radius:8px;padding:12px;text-align:center;">';
    html += '<div style="font-size:11px;color:var(--muted);margin-bottom:4px;">VIX (Fear Gauge)</div>';
    html += '<div style="font-size:22px;font-weight:700;color:' + vixColor + ';">' + vix.toFixed(1) + '</div>';
    html += '<div style="font-size:11px;color:var(--muted);margin-top:4px;">' + (d.vix_signal || '') + '</div>';
    html += '</div>';

    // SPY card
    const spy = d.spy || {};
    const spyColor = spy.above_200ma ? 'var(--green)' : 'var(--red)';
    const spy1m = spy.chg_1m_pct != null ? (spy.chg_1m_pct > 0 ? '+' : '') + spy.chg_1m_pct.toFixed(1) + '%' : '--';
    html += '<div style="background:var(--surface);border-radius:8px;padding:12px;text-align:center;">';
    html += '<div style="font-size:11px;color:var(--muted);margin-bottom:4px;">SPY (S&amp;P 500 ETF)</div>';
    html += '<div style="font-size:22px;font-weight:700;color:' + spyColor + ';">$' + (spy.price || '--') + '</div>';
    html += '<div style="font-size:11px;color:var(--muted);margin-top:4px;">';
    html += (spy.above_200ma ? '<span style="color:var(--green);">Above 200MA</span>' : '<span style="color:var(--red);">Below 200MA</span>');
    html += ' &nbsp;|&nbsp; 1mo: ' + spy1m;
    html += '</div></div>';

    // QQQ card
    const qqq = d.qqq || {};
    const qqqColor = qqq.above_200ma ? 'var(--green)' : 'var(--red)';
    const qqq1m = qqq.chg_1m_pct != null ? (qqq.chg_1m_pct > 0 ? '+' : '') + qqq.chg_1m_pct.toFixed(1) + '%' : '--';
    html += '<div style="background:var(--surface);border-radius:8px;padding:12px;text-align:center;">';
    html += '<div style="font-size:11px;color:var(--muted);margin-bottom:4px;">QQQ (Nasdaq 100 ETF)</div>';
    html += '<div style="font-size:22px;font-weight:700;color:' + qqqColor + ';">$' + (qqq.price || '--') + '</div>';
    html += '<div style="font-size:11px;color:var(--muted);margin-top:4px;">';
    html += (qqq.above_200ma ? '<span style="color:var(--green);">Above 200MA</span>' : '<span style="color:var(--red);">Below 200MA</span>');
    html += ' &nbsp;|&nbsp; 1mo: ' + qqq1m;
    html += '</div></div>';

    html += '</div>'; // end indices grid

    // Sector table
    const sectors = d.sectors || {};
    const sectorNames = Object.keys(sectors);
    if (sectorNames.length) {
      html += '<div style="font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px;">Sector ETF Momentum</div>';
      html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
      html += '<thead><tr style="border-bottom:1px solid var(--border);">';
      html += '<th style="text-align:left;padding:6px 8px;color:var(--muted);font-weight:500;">Sector</th>';
      html += '<th style="text-align:center;padding:6px 8px;color:var(--muted);font-weight:500;">ETF</th>';
      html += '<th style="text-align:right;padding:6px 8px;color:var(--muted);font-weight:500;">1 Month</th>';
      html += '<th style="text-align:right;padding:6px 8px;color:var(--muted);font-weight:500;">3 Month</th>';
      html += '<th style="text-align:center;padding:6px 8px;color:var(--muted);font-weight:500;">vs 200MA</th>';
      html += '</tr></thead><tbody>';

      // Sort by 1mo change descending
      const sorted = sectorNames.slice().sort(function(a, b) {
        return (sectors[b].chg_1m_pct || 0) - (sectors[a].chg_1m_pct || 0);
      });

      sorted.forEach(function(label) {
        const s = sectors[label];
        const chg1m = s.chg_1m_pct != null ? s.chg_1m_pct : null;
        const chg3m = s.chg_3m_pct != null ? s.chg_3m_pct : null;
        const c1 = chg1m == null ? 'var(--muted)' : chg1m >= 0 ? 'var(--green)' : 'var(--red)';
        const c3 = chg3m == null ? 'var(--muted)' : chg3m >= 0 ? 'var(--green)' : 'var(--red)';
        const maLabel = s.above_200ma == null ? '--' : s.above_200ma ? 'Above' : 'Below';
        const maColor = s.above_200ma ? 'var(--green)' : 'var(--red)';
        html += '<tr style="border-bottom:1px solid var(--border-faint,rgba(255,255,255,.05));">';
        html += '<td style="padding:7px 8px;color:var(--fg);">' + label + '</td>';
        html += '<td style="padding:7px 8px;text-align:center;color:var(--muted);">' + (s.symbol || '') + '</td>';
        html += '<td style="padding:7px 8px;text-align:right;color:' + c1 + ';">' + (chg1m != null ? (chg1m >= 0 ? '+' : '') + chg1m.toFixed(1) + '%' : '--') + '</td>';
        html += '<td style="padding:7px 8px;text-align:right;color:' + c3 + ';">' + (chg3m != null ? (chg3m >= 0 ? '+' : '') + chg3m.toFixed(1) + '%' : '--') + '</td>';
        html += '<td style="padding:7px 8px;text-align:center;color:' + maColor + ';">' + maLabel + '</td>';
        html += '</tr>';
      });

      html += '</tbody></table>';
    }

    html += '</div>';
    body.innerHTML = html;
  }

  // Alert dismiss/approve — delegated on document so scanBody + agentBody both work
  document.addEventListener('click', async e => {
    const btn = e.target.closest('[data-alert-id]');
    if (!btn) return;
    const id = btn.dataset.alertId;
    const action = btn.dataset.action;
    if (action === 'approve') await fetch('/api/v1/agent/alerts/' + id + '/approve', { method: 'POST' });
    else if (action === 'deny') await fetch('/api/v1/agent/alerts/' + id + '/deny', { method: 'POST' });
    loadAgentAlerts();
  });

  // ── UNIFIED ORDER TICKET ───────────────────────────────────────
  // Handles both sell (manual, from portfolio) and buy (from AI proposals)
  let pendingProposalId = null;
  const proposalMap = {};

  // Internal state
  let _otSym = '', _otAction = 'SELL', _otOrderType = 'LIMIT';
  let _otPos = null;       // live portfolio position (for sells)
  let _otProposal = null;  // proposal object (for buys from opportunities)
  let _otAdvice = null;    // AI sell recommendation
  let _otHoldType = 'LT'; // for tax calc

  function _otSetStep(n) {
    ['tStep1','tStep2','tStep3'].forEach((id,i) => { $(id).style.display = i+1===n ? 'block' : 'none'; });
    ['tStep1Tab','tStep2Tab','tStep3Tab'].forEach((id,i) => {
      const active = i+1 <= n;
      $(id).style.color = active ? 'var(--accent)' : 'var(--dim)';
      $(id).style.borderBottomColor = i+1 === n ? 'var(--accent)' : 'transparent';
    });
  }

  function _otSetOrderType(ot) {
    _otOrderType = ot;
    $('tLimitBtn').style.background = ot === 'LIMIT' ? 'var(--accent)' : 'transparent';
    $('tLimitBtn').style.color      = ot === 'LIMIT' ? 'white'         : 'var(--muted)';
    $('tMarketBtn').style.background= ot === 'MARKET'? 'var(--accent)' : 'transparent';
    $('tMarketBtn').style.color     = ot === 'MARKET'? 'white'         : 'var(--muted)';
    $('tLimitRow').style.display    = ot === 'LIMIT' ? 'block'         : 'none';
    _otRecalc();
  }

  function _otRecalc() {
    const qty   = Math.max(0, parseInt($('tQtyInput').value) || 0);
    const price = _otOrderType === 'MARKET'
      ? (_otPos ? _otPos.currentPrice : (_otProposal ? parseFloat(_otProposal.limit_price || 0) : 0))
      : (parseFloat($('tLimitInput').value) || 0);
    const total = qty * price;
    $('tEstTotal').textContent = total > 0 ? usd(total) : '—';
    // Tax calc for sells
    if (_otAction === 'SELL' && _otPos && qty > 0 && price > 0) {
      const proceeds = total;
      const cost     = _otPos.avgCost * qty;
      const gain     = proceeds - cost;
      const rate     = _otHoldType === 'LT' ? 0.15 : 0.22;
      const tax      = gain > 0 ? gain * rate : 0;
      const net      = proceeds - tax;
      const gainSign = gain >= 0 ? '+' : '';
      const gainClr  = gain >= 0 ? 'var(--green)' : 'var(--red)';
      const taxEl = $('tTaxSection');
      if (taxEl) {
        $('tTaxProceeds').textContent = usd(proceeds);
        $('tTaxGain').innerHTML = '<span style="color:'+gainClr+'">'+gainSign+usd(gain)+' ('+gainSign+num((gain/Math.max(cost,0.01))*100,1)+'%)</span>';
        $('tTaxOwed').textContent = tax > 0 ? '~'+usd(tax)+' ('+(rate*100)+'% fed)' : 'None';
        $('tTaxNet').textContent = usd(net);
        $('tTaxNet').style.color = net > cost ? 'var(--green)' : net < cost ? 'var(--red)' : 'var(--ink)';
      }
    }
  }

  let _otMarketStatus = '';  // 'OPEN' | 'PRE-MARKET' | 'AFTER HOURS' | 'CLOSED' | 'WEEKEND'

  async function _otLoadMarketStatus() {
    try {
      const today = new Date().toISOString().slice(0, 10);
      const r = await fetch('/api/v1/schwab/market-hours?markets=equity&date=' + today);
      if (!r.ok) return;
      const d = await r.json();
      const eq = d?.equity?.EQ || d?.equity?.equity || Object.values(d?.equity || {})[0];
      if (!eq) return;
      const now = new Date();
      const sessions = eq.sessionHours || {};
      const inWindow = (arr) => {
        if (!arr || !arr[0]) return false;
        const s = new Date(arr[0].start), e = new Date(arr[0].end);
        return now >= s && now <= e;
      };
      const day = now.getDay(); // 0=Sun, 6=Sat
      let status, color, bg;
      if (day === 0 || day === 6) {
        status = 'WEEKEND'; color = '#64748b'; bg = 'rgba(100,116,139,.15)';
      } else if (inWindow(sessions.regularMarket)) {
        status = 'OPEN'; color = 'var(--green)'; bg = 'rgba(34,197,94,.12)';
      } else if (inWindow(sessions.preMarket)) {
        status = 'PRE-MARKET'; color = '#fbbf24'; bg = 'rgba(245,158,11,.13)';
      } else if (inWindow(sessions.postMarket)) {
        status = 'AFTER HOURS'; color = '#fbbf24'; bg = 'rgba(245,158,11,.13)';
      } else {
        status = 'CLOSED'; color = '#64748b'; bg = 'rgba(100,116,139,.15)';
      }
      _otMarketStatus = status;
      const pill = $('tMarketPill');
      if (pill) {
        pill.textContent = status;
        pill.style.color = color;
        pill.style.background = bg;
        pill.style.display = 'inline-block';
      }
    } catch(_) {}
  }

  async function _otLoadQuote(sym) {
    try {
      const r = await fetch('/api/v1/schwab/quotes?symbols=' + encodeURIComponent(sym));
      if (!r.ok) return;
      const d = await r.json();
      const q = d[sym] || d[sym.toUpperCase()];
      if (!q) return;
      const ref = q.reference || q;
      const qrt = q.quote || q;
      const last   = qrt.lastPrice || qrt.mark || qrt.close || 0;
      const change = qrt.netChange || 0;
      const pchg   = qrt.netPercentChange || (last > 0 ? change/last*100 : 0);
      const bid    = qrt.bidPrice || qrt.bid || 0;
      const ask    = qrt.askPrice || qrt.ask || 0;
      const dayLo  = qrt.lowPrice  || qrt.low  || 0;
      const dayHi  = qrt.highPrice || qrt.high || 0;
      const wkLo   = ref['52WeekLow']  || ref.fiftyTwoWeekLow  || 0;
      const wkHi   = ref['52WeekHigh'] || ref.fiftyTwoWeekHigh || 0;
      const clr = change >= 0 ? 'var(--green)' : 'var(--red)';
      $('tPrice').textContent = usd(last);
      $('tChange').textContent = (change >= 0 ? '+' : '')+num(change,2)+' ('+num(pchg,2)+'%)';
      $('tChange').style.color = clr;
      $('tBid').textContent    = bid  > 0 ? usd(bid)  : '—';
      $('tAsk').textContent    = ask  > 0 ? usd(ask)  : '—';
      $('tDayRange').textContent = (dayLo > 0 && dayHi > 0) ? num(dayLo,2)+' – '+num(dayHi,2) : '—';
      $('t52Wk').textContent     = (wkLo  > 0 && wkHi  > 0) ? num(wkLo,2)+' – '+num(wkHi,2)  : '—';
      // Update limit input to current price if still default
      if (_otOrderType === 'LIMIT' && last > 0 && !parseFloat($('tLimitInput').value)) {
        $('tLimitInput').value = last.toFixed(2);
      }
      _otRecalc();
    } catch(_) {}
  }

  function openOrderTicket(opts) {
    // opts: { sym, action:'SELL'|'BUY', pos?, proposal? }
    _otSym      = opts.sym;
    _otAction   = opts.action || 'SELL';
    _otPos      = opts.pos || null;
    _otProposal = opts.proposal || null;
    _otAdvice   = null;
    _otHoldType = 'LT';

    // Header
    $('tSym').textContent    = _otSym;
    $('tSymName').textContent = _otAction === 'SELL' ? 'Sell Position' : 'Buy Opportunity';
    $('tPrice').textContent  = '—';
    $('tChange').textContent = '—';
    $('tBid').textContent = $('tAsk').textContent = $('tDayRange').textContent = $('t52Wk').textContent = '—';

    // Pre-fill qty
    let defaultQty = 1;
    let defaultPrice = 0;
    if (_otAction === 'SELL' && _otPos) {
      defaultQty   = Math.floor(_otPos.qty);
      defaultPrice = _otPos.currentPrice;
      $('tQtyContext').textContent = 'of ' + Math.floor(_otPos.qty) + ' held · avg cost ' + usd(_otPos.avgCost);
    } else if (_otAction === 'BUY' && _otProposal) {
      defaultQty   = parseInt(_otProposal.quantity) || 1;
      defaultPrice = parseFloat(_otProposal.limit_price) || 0;
      $('tQtyContext').textContent = 'proposed by AI';
    }
    $('tQtyInput').value   = defaultQty;
    $('tLimitInput').value = defaultPrice > 0 ? defaultPrice.toFixed(2) : '';

    // Order type
    const ot = (_otProposal && _otProposal.order_type) ? _otProposal.order_type.toUpperCase() : 'LIMIT';
    _otSetOrderType(ot);

    // AI reasoning from proposal
    const aiEl = $('tAiReasoning');
    if (_otProposal && _otProposal.reasoning) {
      aiEl.textContent = _otProposal.reasoning;
      aiEl.style.display = 'block';
    } else {
      aiEl.style.display = 'none';
    }

    // Tax section visibility
    const taxEl = $('tTaxSection');
    if (taxEl) taxEl.style.display = _otAction === 'SELL' ? 'block' : 'none';
    const aiBtn = $('tAiSellBtn');
    if (aiBtn) aiBtn.style.display = _otAction === 'SELL' ? 'flex' : 'none';

    // AI advice panel reset
    _otResetAdvice();

    // Step 1, clear status
    _otSetStep(1);
    $('tStep1Status').textContent = '';
    $('tradeOverlay').style.display = 'flex';

    // Load live quote + market status async
    _otLoadQuote(_otSym);
    _otLoadMarketStatus();
  }

  function closeTradeReview() {
    $('tradeOverlay').style.display = 'none';
    pendingProposalId = null;
    _otProposal = null; _otPos = null;
    const pill = $('tMarketPill'); if (pill) pill.style.display = 'none';
    _otMarketStatus = '';
  }

  // Compatibility shims for callers
  function openTradeConfirm(proposal) {
    openOrderTicket({ sym: proposal.symbol, action: proposal.action || 'BUY', proposal });
    pendingProposalId = proposal.id;
  }
  function openSellModal(sym) {
    const pos = positions.find(p => p.symbol === sym);
    if (!pos) return;
    openOrderTicket({ sym, action: 'SELL', pos });
  }
  function closeSellModal() { closeTradeReview(); }

  // Hold-type toggle wiring (tax calc in sell ticket)
  function _otSetHoldType(ht) {
    _otHoldType = ht;
    $('tHoldLT').style.background  = ht === 'LT' ? 'var(--accent)' : 'transparent';
    $('tHoldLT').style.color       = ht === 'LT' ? 'white'         : 'var(--muted)';
    $('tHoldLT').style.borderColor = ht === 'LT' ? 'var(--accent)' : 'var(--line)';
    $('tHoldST').style.background  = ht === 'ST' ? 'var(--accent)' : 'transparent';
    $('tHoldST').style.color       = ht === 'ST' ? 'white'         : 'var(--muted)';
    $('tHoldST').style.borderColor = ht === 'ST' ? 'var(--accent)' : 'var(--line)';
    _otRecalc();
  }

  // AI advice state + helpers
  let _otAiAdvice = null;

  function _otResetAdvice() {
    _otAiAdvice = null;
    const loadEl = $('tAiLoading'); if (loadEl) loadEl.style.display = 'none';
    const resEl  = $('tAiResult');  if (resEl)  resEl.style.display  = 'none';
    const getBtn = $('tGetAiBtn');
    if (getBtn) {
      getBtn.style.display = 'flex';
      getBtn.textContent = '';
      getBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>Get AI Recommendation';
      getBtn.style.color = '#93c5fd';
      getBtn.style.borderColor = 'rgba(37,99,235,.25)';
    }
  }

  async function _otGetAiAdvice() {
    if (!_otPos) return;
    const pos = _otPos;
    $('tGetAiBtn').style.display = 'none';
    $('tAiResult').style.display = 'none';
    $('tAiLoading').style.display = 'block';
    _otAiAdvice = null;
    try {
      const r = await fetch('/api/v1/agent/analyze-sell', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          symbol: _otSym,
          qty_held: pos.qty,
          avg_cost: pos.avgCost,
          current_price: pos.currentPrice,
          total_pnl_pct: pos.totalPct,
          day_pnl_pct: pos.dayPct,
          portfolio_weight_pct: pos.weight,
        }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || 'Analysis failed');
      _otAiAdvice = await r.json();
      $('tAiLoading').style.display = 'none';
      _otRenderAiAdvice(_otAiAdvice, pos);
      $('tAiResult').style.display = 'block';
    } catch(e) {
      $('tAiLoading').style.display = 'none';
      const btn = $('tGetAiBtn');
      btn.style.display = 'flex';
      btn.textContent = 'Retry — ' + e.message;
      btn.style.color = 'var(--red)';
      btn.style.borderColor = 'rgba(239,68,68,.3)';
    }
  }

  function _otRenderAiAdvice(advice, pos) {
    const colors = {
      SELL_ALL:     {bg:'rgba(239,68,68,.15)',  color:'#f87171', label:'SELL ALL'},
      SELL_PARTIAL: {bg:'rgba(245,158,11,.12)', color:'#fbbf24', label:'SELL PARTIAL'},
      TRIM:         {bg:'rgba(245,158,11,.12)', color:'#fbbf24', label:'TRIM'},
      HOLD:         {bg:'rgba(34,197,94,.10)',  color:'#4ade80', label:'HOLD'},
    };
    const cfg = colors[advice.action] || {bg:'var(--surface3)', color:'var(--muted)', label: advice.action || 'UNKNOWN'};
    const actionEl = $('tAiAction');
    actionEl.textContent = cfg.label;
    actionEl.style.background = cfg.bg;
    actionEl.style.color = cfg.color;
    $('tAiHeadline').textContent = advice.headline || '';
    $('tAiReasoning2').textContent = advice.reasoning || '';
    const riskEl = $('tAiRisk');
    if (advice.risk_factors) { riskEl.textContent = 'Risk: ' + advice.risk_factors; riskEl.style.display = 'block'; }
    else { riskEl.style.display = 'none'; }
    const applyBtn = $('tAiApplyBtn');
    const canApply = ['SELL_ALL','SELL_PARTIAL','TRIM'].includes(advice.action) && advice.suggested_quantity;
    if (canApply) {
      applyBtn.style.display = 'inline-block';
      const qty = Math.min(Math.floor(pos.qty), Math.max(1, advice.suggested_quantity));
      applyBtn.textContent = 'Apply: sell ' + qty + ' shares' + (advice.suggested_price ? ' @ $' + parseFloat(advice.suggested_price).toFixed(2) : '');
    } else {
      applyBtn.style.display = 'none';
    }
  }

  function _otApplyAiAdvice() {
    if (!_otAiAdvice || !_otPos) return;
    const qty = Math.min(Math.floor(_otPos.qty), Math.max(1, _otAiAdvice.suggested_quantity || Math.floor(_otPos.qty)));
    $('tQtyInput').value = qty;
    if (_otAiAdvice.suggested_price) {
      _otSetOrderType('LIMIT');
      $('tLimitInput').value = parseFloat(_otAiAdvice.suggested_price).toFixed(2);
    } else {
      _otSetOrderType('MARKET');
    }
    _otRecalc();
    $('tAiApplyBtn').textContent = 'Applied';
    $('tAiApplyBtn').disabled = true;
    // Store advice reasoning for order submission
    _otAdvice = _otAiAdvice;
  }

  // Qty stepper
  $('tQtyMinus').onclick = () => { const v = parseInt($('tQtyInput').value)||1; $('tQtyInput').value = Math.max(1,v-1); _otRecalc(); };
  $('tQtyPlus').onclick  = () => { const v = parseInt($('tQtyInput').value)||0; $('tQtyInput').value = v+1;             _otRecalc(); };
  $('tQtyInput').oninput = _otRecalc;
  $('tLimitInput').oninput = _otRecalc;
  $('tLimitBtn').onclick  = () => _otSetOrderType('LIMIT');
  $('tMarketBtn').onclick = () => _otSetOrderType('MARKET');
  $('tHoldLT').onclick = () => _otSetHoldType('LT');
  $('tHoldST').onclick = () => _otSetHoldType('ST');

  function tradeGoReview() {
    const qty = parseInt($('tQtyInput').value) || 0;
    if (qty <= 0) { $('tStep1Status').textContent = 'Enter a valid quantity.'; return; }
    if (_otAction === 'SELL' && _otPos && qty > Math.floor(_otPos.qty)) {
      $('tStep1Status').textContent = 'You only hold ' + Math.floor(_otPos.qty) + ' shares.'; return;
    }
    if (_otOrderType === 'LIMIT' && !(parseFloat($('tLimitInput').value) > 0)) {
      $('tStep1Status').textContent = 'Enter a valid limit price.'; return;
    }
    $('tStep1Status').textContent = '';
    const price = _otOrderType === 'MARKET' ? null : parseFloat($('tLimitInput').value);
    const total = price && qty ? price * qty : null;
    const priceStr = price ? '@ $' + price.toFixed(2) + ' LIMIT' : '@ MARKET';
    $('tReviewHeadline').textContent = _otAction + ' ' + qty + ' ' + _otSym + ' ' + priceStr;
    const rows = [
      ['Action',     _otAction],
      ['Shares',     qty],
      ['Order Type', _otOrderType],
      price ? ['Limit Price', usd(price)] : null,
      total ? ['Estimated Total', usd(total)] : null,
      _otAction === 'SELL' && _otPos ? ['Avg Cost Basis', usd(_otPos.avgCost)] : null,
    ].filter(Boolean);
    $('tReviewRows').innerHTML = rows.map(([l,v]) =>
      '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line);font-size:13px;">'
      + '<span style="color:var(--muted);">'+l+'</span><span style="font-weight:600;color:var(--ink);">'+v+'</span></div>'
    ).join('');
    $('tReviewMeta').textContent = (_otProposal ? 'AI Proposal · ' : 'Manual Order · ') + _otSymName();
    $('tStep2Status').textContent = '';
    $('tPlaceBtn').disabled = false;
    $('tPlaceBtn').textContent = 'Place Order';
    // Market-hours warning
    const mw = $('tMarketWarning');
    if (mw) {
      const offHours = _otMarketStatus && _otMarketStatus !== 'OPEN';
      if (_otOrderType === 'MARKET' && offHours) {
        const nextOpen = (_otMarketStatus === 'WEEKEND') ? "Monday open" : 'the next market open';
        mw.textContent = 'Market is currently ' + _otMarketStatus.toLowerCase() + '. This market order will execute at ' + nextOpen + ' — the fill price may differ significantly from the current quote.';
        mw.style.display = 'block';
      } else if (offHours) {
        const nextOpen = (_otMarketStatus === 'WEEKEND') ? 'Monday' : 'next session';
        mw.textContent = 'Market is currently ' + _otMarketStatus.toLowerCase() + '. Your limit order will queue and execute at ' + nextOpen + ' if the price reaches your limit.';
        mw.style.display = 'block';
      } else {
        mw.style.display = 'none';
      }
    }
    _otSetStep(2);
  }

  function tradeGoBack() { _otSetStep(1); }

  function _otSymName() { return _otSym; }

  async function confirmTrade() {
    const qty = parseInt($('tQtyInput').value) || 0;
    const price = _otOrderType === 'LIMIT' ? parseFloat($('tLimitInput').value) : null;
    const btn = $('tPlaceBtn');
    btn.disabled = true; btn.textContent = 'Placing order...';
    $('tStep2Status').textContent = 'Running risk checks...'; $('tStep2Status').style.color = 'var(--muted)';
    try {
      let r, d;
      if (_otAction === 'SELL') {
        const payload = { symbol: _otSym, action: 'SELL', quantity: qty, order_type: _otOrderType, limit_price: price, reasoning: _otAdvice ? _otAdvice.reasoning : 'Manual sell from dashboard' };
        r = await fetch('/api/v1/agent/place-sell-order', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
        d = await r.json();
      } else {
        // BUY — execute the existing proposal with user-adjusted qty and price
        const buyPayload = {};
        if (qty) buyPayload.quantity = qty;
        if (price) buyPayload.limit_price = price;
        r = await fetch('/api/v1/agent/proposals/' + pendingProposalId + '/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buyPayload),
        });
        d = await r.json();
      }
      if (!r.ok) throw new Error(d.detail || 'Order failed');
      $('tStep3Headline').textContent = 'Order Placed';
      $('tStep3Detail').textContent = _otAction + ' ' + qty + ' ' + _otSym + (price ? ' @ $'+price.toFixed(2)+' LIMIT' : ' @ MARKET') + ' has been sent to Schwab.';
      _otSetStep(3);
      pendingProposalId = null;
      setTimeout(() => { loadDashboard(); loadAgentAlerts(); }, 1500);
    } catch(e) {
      $('tStep2Status').textContent = e.message; $('tStep2Status').style.color = 'var(--red)';
      btn.disabled = false; btn.textContent = 'Place Order';
    }
  }

  // Sell buttons outside the portfolio table (opportunity cards) — handled at document level
  document.addEventListener('click', e => {
    if (e.target.closest('#posBody')) return;   // portfolio table handled separately
    const sellBtn = e.target.closest('.sell-pos-btn');
    if (!sellBtn) return;
    openSellModal(sellBtn.dataset.sym);
  });

  // Delegate execute/skip clicks — on document so scanBody + agentBody both fire
  document.addEventListener('click', async e => {
    const btn = e.target.closest('[data-pid]');
    if (!btn) return;
    const pid = btn.dataset.pid;
    const action = btn.dataset.action;

    if (action === 'skip') {
      const card = btn.closest('.prop-card');
      if (card) { card.style.opacity = '.35'; card.style.pointerEvents = 'none'; }
      await fetch('/api/v1/agent/proposals/' + pid + '/cancel', { method: 'POST' });
      loadAgentAlerts();
      return;
    }

    if (action === 'execute') {
      const proposal = proposalMap[pid];
      if (!proposal) return;
      openTradeConfirm(proposal);
    }
  });

  // ── Portfolio Health Score ─────────────────────────────────────
  function updateHealthScore(pos) {
    let score = 100;
    const reasons = [];

    // Concentration penalty
    const maxWeight = Math.max(...pos.map(p => p.weight || 0), 0);
    if (maxWeight >= 40) { score -= 25; reasons.push('Heavy concentration'); }
    else if (maxWeight >= 25) { score -= 10; reasons.push('Moderate concentration'); }

    // Drawdown penalties
    pos.forEach(p => {
      if (p.totalPct <= -25) { score -= 15; reasons.push(p.symbol + ' down ' + p.totalPct.toFixed(0) + '%'); }
      else if (p.totalPct <= -15) { score -= 8; }
      else if (p.totalPct <= -10) { score -= 4; }
    });

    // Diversification bonus
    const n = pos.filter(p => p.mktVal > 0).length;
    if (n >= 6) score += 5;
    else if (n <= 1) score -= 10;

    score = Math.max(0, Math.min(100, Math.round(score)));
    const color = score >= 80 ? '#3fb950' : score >= 55 ? '#fbbf24' : '#f85149';
    const label = score >= 80 ? 'Strong' : score >= 55 ? 'Fair' : 'At Risk';

    $('healthScore').textContent = score;
    $('healthScore').style.color = color;
    $('healthLabel').textContent = label + (reasons.length ? ' · ' + reasons[0] : '');

    // SVG arc: circumference = 2π×20 ≈ 125.66
    const circ = 125.66;
    const offset = circ * (1 - score / 100);
    const arc = $('healthArc');
    if (arc) { arc.style.strokeDashoffset = offset; arc.style.stroke = color; }
  }

  // ── AI Morning Briefing ────────────────────────────────────────
  let _briefingLoaded = false;
  async function loadBriefing(force) {
    const card = $('briefingCard');
    if (!force && _briefingLoaded) return;
    try {
      const r = await fetch('/api/v1/agent/briefing' + (force ? '?force=true' : ''));
      if (!r.ok) return;
      const d = await r.json();
      const b = d.briefing;
      if (!b) return;

      $('briefingHeadline').textContent = b.headline || '';
      $('briefingBullets').innerHTML = (b.bullets || []).map(bl =>
        '<div class="briefing-bullet">' + _esc(bl) + '</div>'
      ).join('');
      $('briefingAction').textContent = b.action || '';
      $('briefingWatch').textContent = b.top_watch ? '👁 ' + b.top_watch : '';

      // Age display
      if (b.generated_at) {
        const age = Math.round((Date.now() - new Date(b.generated_at).getTime()) / 60000);
        $('briefingAge').textContent = age < 2 ? 'just now' : age + 'm ago';
      }
      card.style.display = '';
      _briefingLoaded = true;
    } catch(_) {}
  }

  // ── AI Quick Take (drill panel) ────────────────────────────────
  async function loadQuickTake(symbol) {
    $('quickTakeText').textContent = 'Analyzing ' + symbol + '...';
    $('quickTakeText').style.color = 'var(--muted)';
    const sigEl = $('quickTakeSignal');
    sigEl.style.display = 'none';
    try {
      const r = await fetch('/api/v1/advisor/quick-take/' + encodeURIComponent(symbol));
      if (!r.ok) return;
      const d = await r.json();
      $('quickTakeText').textContent = d.take || '';
      $('quickTakeText').style.color = 'var(--muted)';
      if (d.signal) {
        const sigColors = { BUY:'#3fb950', HOLD:'#fbbf24', TRIM:'#fb923c', AVOID:'#f85149' };
        sigEl.textContent = d.signal;
        sigEl.style.background = (sigColors[d.signal] || '#6e7681') + '1a';
        sigEl.style.color = sigColors[d.signal] || '#6e7681';
        sigEl.style.display = '';
      }
    } catch(_) {
      $('quickTakeText').textContent = 'Unable to load analysis.';
    }
  }

  // ── Mute symbol handler (delegated from agentBody) ─────────────
  $('agentBody').addEventListener('click', async e => {
    const btn = e.target.closest('.btn-mute');
    if (!btn) return;
    const sym = btn.dataset.sym;
    if (!sym) return;
    btn.disabled = true;
    btn.textContent = 'Muting...';
    try {
      await fetch('/api/v1/agent/mute/' + encodeURIComponent(sym), { method: 'POST' });
      btn.textContent = 'Muted 7d';
      btn.style.color = '#fbbf24';
      btn.style.borderColor = '#fbbf24';
    } catch(_) {
      btn.textContent = 'Error';
      btn.disabled = false;
    }
  });

  // ── What-If Simulator ─────────────────────────────────────────
  // ── Markdown renderer with Python code-block runner ──────────────
  function _renderMd(text) {
    const NL = String.fromCharCode(10);
    function esc(s) { return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

    // Parse a pipe-delimited table block into HTML
    function renderTable(rows) {
      let html = '<div style="overflow-x:auto;margin:10px 0;">'
        + '<table style="width:100%;border-collapse:collapse;font-size:12.5px;">'
        + '<thead>';
      const headers = rows[0].split("|").map(c => c.trim()).filter(Boolean);
      html += "<tr>" + headers.map(h =>
        '<th style="text-align:left;padding:7px 12px;border-bottom:2px solid var(--line2);color:var(--muted);font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.06em;">'
        + esc(h) + "</th>").join("") + "</tr></thead><tbody>";
      for (let r = 2; r < rows.length; r++) {
        const cells = rows[r].split("|").map(c => c.trim()).filter(Boolean);
        if (!cells.length) continue;
        html += "<tr>" + cells.map((c, ci) =>
          '<td style="padding:7px 12px;border-bottom:1px solid var(--line);color:var(--ink);">'
          + _inlineMd(esc(c)) + "</td>").join("") + "</tr>";
      }
      return html + "</tbody></table></div>";
    }

    function _inlineMd(s) {
      s = s.replace(/[*][*](.+?)[*][*]/g, "<strong>$1</strong>");
      s = s.replace(/[*](.+?)[*]/g, '<em style="color:#a5b4c4;">$1</em>');
      s = s.replace(/`([^`]+)`/g, '<code style="background:#0A0F14;border-radius:3px;padding:1px 5px;font-size:11.5px;color:#7dd3fc;">$1</code>');
      return s;
    }

    let _codeIdx = 0;
    const out = [];
    const parts = text.split("```");
    for (let i = 0; i < parts.length; i++) {
      if (i % 2 === 0) {
        // Split into lines, detect table blocks, render the rest as markdown
        const rawLines = parts[i].split(NL);
        let j = 0;
        let curBlock = [];

        function flushBlock() {
          if (!curBlock.length) return;
          let s = esc(curBlock.join(NL));
          s = s.replace(/^#{1,3} (.+)$/gm, '<strong style="font-size:14px;display:block;margin:14px 0 4px;color:#E8EDF5;">$1</strong>');
          s = _inlineMd(s);
          s = s.replace(/^[-*] (.+)$/gm, '<div style="padding-left:14px;position:relative;line-height:1.7;"><span style="position:absolute;left:0;color:#2563EB;">&#x2022;</span>$1</div>');
          // Paragraph breaks
          const blk = s.split(NL + NL).map(p => p.split(NL).join("<br>")).filter(Boolean).join("<br><br>");
          if (blk) out.push(blk);
          curBlock = [];
        }

        while (j < rawLines.length) {
          const ln = rawLines[j];
          // Detect table: current line starts with |, next line is |---|
          const isSep = (s) => /^[|][ \t:|:-]+[|]/.test(s.trim());
          if (ln.trim().startsWith("|") && j+1 < rawLines.length && isSep(rawLines[j+1])) {
            flushBlock();
            const tRows = [];
            while (j < rawLines.length && rawLines[j].trim().startsWith("|")) {
              tRows.push(rawLines[j].trim());
              j++;
            }
            out.push(renderTable(tRows));
          } else {
            curBlock.push(ln);
            j++;
          }
        }
        flushBlock();
      } else {
        const nlPos = parts[i].indexOf(NL);
        const lang  = nlPos >= 0 ? parts[i].slice(0, nlPos).trim().toLowerCase() : "";
        const code  = nlPos >= 0 ? parts[i].slice(nlPos + 1) : parts[i];
        const idx = _codeIdx++;
        let encodedCode = "";
        try { encodedCode = btoa(unescape(encodeURIComponent(code))); } catch(_) {}
        const runBtn = (lang === "python")
          ? '<button onclick="runCodeBlock(this)" data-code="' + encodedCode + '" data-code-idx="' + idx + '" style="margin-top:8px;background:rgba(37,99,235,.12);border:1px solid rgba(37,99,235,.3);color:#93c5fd;border-radius:6px;padding:5px 12px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:5px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>Run</button><div class="code-result" id="cres-' + idx + '" style="margin-top:8px;display:none;"></div>'
          : "";
        out.push('<pre style="background:#0A0F14;border:1px solid #1C2530;border-radius:8px;padding:12px 14px;overflow-x:auto;margin:10px 0;"><code style="font-family:Menlo,Monaco,monospace;font-size:12px;color:#e2e8f0;line-height:1.6;">'
          + esc(code) + "</code></pre>" + runBtn);
      }
    }
    return out.join("");
  }

  function esc_simple(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  // Execute a Python code block and render the result inline
  async function runCodeBlock(btn) {
    const idx = btn.dataset.codeIdx;
    const resEl = document.getElementById('cres-' + idx);
    if (!resEl) return;
    let code;
    try { code = decodeURIComponent(escape(atob(btn.dataset.code))); } catch(_) { return; }

    btn.disabled = true;
    btn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> Running...';
    resEl.style.display = 'block';
    resEl.innerHTML = '<span style="font-size:12px;color:var(--muted);">Executing...</span>';

    try {
      const r = await fetch('/api/v1/advisor/exec-python', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ code }),
      });
      const d = await r.json();
      let html = '';
      if (d.error) html += '<pre style="background:#1a0a0a;border:1px solid rgba(239,68,68,.3);border-radius:6px;padding:8px 12px;font-size:11.5px;color:#f87171;overflow-x:auto;margin:4px 0;white-space:pre-wrap;">' + esc_simple(d.error) + '</pre>';
      if (d.output && d.output.trim()) html += '<pre style="background:#0A0F14;border-radius:6px;padding:8px 12px;font-size:12px;color:#a5b4c4;overflow-x:auto;margin:4px 0;">' + esc_simple(d.output) + '</pre>';
      if (d.image_b64) html += '<img src="data:image/png;base64,' + d.image_b64 + '" style="max-width:100%;border-radius:8px;margin-top:6px;display:block;">';
      if (!html) html = '<span style="font-size:12px;color:var(--muted);">No output.</span>';
      resEl.innerHTML = html;
      // Scroll chat to show chart
      const msgs = document.getElementById('chatMessages');
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
    } catch(e) {
      resEl.innerHTML = '<span style="font-size:12px;color:var(--red);">Error: ' + esc_simple(e.message) + '</span>';
    }
    btn.style.display = 'none'; // hide Run button after execution
  }

  // Auto-run all Python blocks inside a given DOM element
  function autoRunCodeBlocks(el) {
    if (!el) return;
    el.querySelectorAll('button[data-code-idx]').forEach(btn => {
      if (btn.dataset.code) runCodeBlock(btn);
    });
  }

  function openWhatif() { $('whatifOverlay').style.display = 'flex'; $('whatifInput').focus(); }
  function closeWhatif() { $('whatifOverlay').style.display = 'none'; }

  let _whatifBusy = false;

  async function runWhatif() {
    const q = $('whatifInput').value.trim();
    if (!q || _whatifBusy) return;
    _whatifBusy = true;
    const askBtn = $('whatifOverlay').querySelector('button[onclick="runWhatif()"]');
    if (askBtn) { askBtn.disabled = true; askBtn.textContent = '...'; }
    $('whatifResult').innerHTML = '<span style="color:var(--muted);font-size:13px;">Thinking...</span>';

    const portfolio = positions.map(p =>
      p.symbol + ': ' + num(p.qty,4) + ' shares @ avg $' + usd(p.avgCost) +
      ', mkt $' + usd(p.mktVal) + ', P&L ' + pct(p.totalPct)
    ).join('\\n');

    const systemCtx = 'Portfolio context (live data):\\n' + portfolio;
    const fullQ = q + '\\n\\n' + systemCtx;

    let text = '';
    try {
      const r = await fetch('/api/v1/advisor/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: fullQ, history: [] }),
      });
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      $('whatifResult').textContent = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const line of dec.decode(value).split('\\n')) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6);
          if (data === '[DONE]') break;
          try {
            const obj = JSON.parse(data);
            if (obj.text) { text += obj.text; $('whatifResult').innerHTML = _renderMd(text); }
          } catch(_) {}
        }
      }
      autoRunCodeBlocks($('whatifResult'));
    } catch(e) {
      $('whatifResult').innerHTML = '<span style="color:var(--red);">Error: ' + e.message + '</span>';
    } finally {
      _whatifBusy = false;
      if (askBtn) { askBtn.disabled = false; askBtn.textContent = 'Ask'; }
    }
  }

  loadAgentAlerts();
  setInterval(loadAgentAlerts, 60000); // refresh alerts every 1 min
  loadBriefing();                       // load briefing from cache (fast)
  loadJournal();

  // ── Trade Journal ─────────────────────────────────────────────
  function jstat(label, valHtml) {
    return '<div class="j-stat"><div class="j-stat-label">'+label+'</div><div class="j-stat-val">'+valHtml+'</div></div>';
  }

  async function loadJournal() {
    try {
      const [scR, tradesR] = await Promise.all([
        fetch('/api/v1/journal/scorecard?limit=500'),
        fetch('/api/v1/journal/completed-trades?limit=50'),
      ]);

      const hasData = scR.ok || tradesR.ok;
      if (!hasData) {
        $('journalStatus').textContent = 'No trades synced yet';
        $('journalScorecard').innerHTML = '';
        $('journalBody').innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted);font-size:13px;">Sync then Rebuild to populate your journal.</div>';
        return;
      }

      if (scR.ok) {
        const sc = await scR.json();
        const s = sc.summary || {};
        const total = s.total_trades || 0;
        $('journalTradeCount').textContent = total ? total + ' trades' : '';
        if (total > 0) {
          const wr = ((s.win_rate || 0) * 100).toFixed(1);
          const pf = (s.profit_factor || 0).toFixed(2);
          const ex = (s.expectancy || 0).toFixed(2);
          $('journalScorecard').innerHTML =
            jstat('Win Rate',      (s.win_rate||0) >= 0.5 ? span('gain', wr+'%') : span('loss', wr+'%'))
            + jstat('Profit Factor', parseFloat(pf) >= 1.5 ? span('gain', pf) : pf)
            + jstat('Expectancy',   (s.expectancy||0) >= 0 ? span('gain', '$'+ex) : span('loss', '$'+ex))
            + jstat('Total P&L',    span(gc(s.gross_pnl||0), usd(s.gross_pnl||0)))
            + jstat('Avg Win',      span('gain', usd(s.avg_win||0)))
            + jstat('Avg Loss',     span('loss', usd(s.avg_loss||0)));
        } else {
          $('journalScorecard').innerHTML = '<div style="padding:14px 18px;color:var(--muted);font-size:13px;">No completed trades yet.</div>';
        }
      }

      if (tradesR.ok) {
        const trades = await tradesR.json();
        if (!trades.length) {
          $('journalBody').innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted);font-size:13px;">No completed trades yet. Sync &amp; Rebuild to populate.</div>';
        } else {
          $('journalBody').innerHTML = '<table>'
            + '<thead><tr>'
            + '<th style="text-align:left">Symbol</th><th style="text-align:left">Side</th>'
            + '<th>Qty</th><th>Entry</th><th>Exit</th>'
            + '<th>P&amp;L</th><th>Return</th><th>Hold</th><th>Closed</th>'
            + '</tr></thead>'
            + '<tbody>' + trades.map(t => {
                const retPct = t.entry_price > 0 ? (t.exit_price - t.entry_price) / t.entry_price * (t.side === 'long' ? 100 : -100) : 0;
                const holdStr = t.hold_minutes != null ? (t.hold_minutes < 60 ? t.hold_minutes+'m' : (t.hold_minutes/60).toFixed(1)+'h') : '—';
                const exitDate = t.exit_time ? new Date(t.exit_time).toLocaleDateString() : '—';
                const sideColor = t.side === 'long' ? 'var(--green)' : 'var(--red)';
                return '<tr>'
                  +'<td><span class="sym">'+t.symbol+'</span></td>'
                  +'<td><span style="color:'+sideColor+';font-weight:600;font-size:12px">'+t.side.toUpperCase()+'</span></td>'
                  +'<td>'+t.quantity+'</td>'
                  +'<td>'+usd(t.entry_price)+'</td>'
                  +'<td>'+usd(t.exit_price)+'</td>'
                  +'<td>'+span(gc(t.gross_pnl||0), usd(t.gross_pnl||0))+'</td>'
                  +'<td>'+span(gc(retPct), (retPct>=0?'+':'')+retPct.toFixed(2)+'%')+'</td>'
                  +'<td style="color:var(--muted)">'+holdStr+'</td>'
                  +'<td style="color:var(--muted);font-size:12px">'+exitDate+'</td>'
                  +'</tr>';
              }).join('')
            + '</tbody></table>';
        }
      }
      $('journalStatus').textContent = 'Updated '+new Date().toLocaleTimeString();
    } catch(_) {
      $('journalStatus').textContent = 'Failed';
    }
  }

  async function syncJournal() {
    const syncBtn = $('journalSyncBtn');
    const rebuildBtn = $('journalRebuildBtn');
    const stopSync = _animBtn(syncBtn, 'Fetching 1yr', '\u21bb Fetch 1yr', 4000);
    try {
      const r = await fetch('/api/v1/journal/sync?days=365', { method: 'POST' });
      if (!r.ok) throw new Error();
      const d = await r.json();
      stopSync(d.orders_synced + ' orders — recalculating\u2026');
      // Auto-rebuild immediately after sync so trades appear without a second click
      const stopRebuild = _animBtn(rebuildBtn, 'Recalculating', '\u21bb Recalculate', 4000);
      try {
        const r2 = await fetch('/api/v1/journal/rebuild-completed-trades', { method: 'POST' });
        if (!r2.ok) throw new Error();
        const d2 = await r2.json();
        syncBtn.textContent = d2.completed_trade_count + ' trades found';
        stopRebuild(d2.completed_trade_count + ' trades');
        setTimeout(() => { syncBtn.disabled = false; syncBtn.textContent = '\u21bb Fetch 1yr'; }, 4000);
      } catch(_) {
        syncBtn.textContent = d.orders_synced + ' orders synced';
        stopRebuild('Failed');
        setTimeout(() => { syncBtn.disabled = false; syncBtn.textContent = '\u21bb Fetch 1yr'; }, 2000);
      }
      loadJournal();
    } catch(_) {
      stopSync('Failed');
    }
  }

  async function rebuildTrades() {
    const btn = $('journalRebuildBtn');
    const stop = _animBtn(btn, 'Recalculating', '\u21bb Recalculate', 3000);
    try {
      const r = await fetch('/api/v1/journal/rebuild-completed-trades', { method: 'POST' });
      if (!r.ok) throw new Error();
      const d = await r.json();
      stop(d.completed_trade_count + ' trades');
      loadJournal();
    } catch(_) {
      stop('Failed');
    }
  }

  // ── News Feed ─────────────────────────────────────────────────
  let _newsLastLoaded = 0;

  function _renderNewsItems(items) {
    if (!items.length) return '<div style="padding:20px;text-align:center;color:var(--muted);font-size:13px;">No recent news found.</div>';
    return items.map(it => {
      const svCls = it.severity === 'HIGH' ? 'news-badge-high' : it.severity === 'MEDIUM' ? 'news-badge-medium' : 'news-badge-low';
      const matDot = it.material ? '<span style="color:var(--red);margin-right:4px">&#9679;</span>' : '';
      return '<div class="news-item">'
        +'<div class="news-header">'
        +'<span class="news-sym">'+it.symbol+'</span>'
        +'<a href="'+it.link+'" target="_blank" rel="noopener" class="news-title">'+matDot+it.title+'</a>'
        +'</div>'
        +(it.take ? '<div class="news-take">'+it.take+'</div>' : '')
        +'<div class="news-footer">'
        +'<span class="'+svCls+'">'+it.severity+'</span>'
        +'<span>\u00b7</span>'
        +'<span>'+it.publisher+'</span>'
        +'<span>\u00b7</span>'
        +'<span>'+it.published_str+'</span>'
        +'</div>'
        +'</div>';
    }).join('');
  }

  async function loadNews(force) {
    if (!force && Date.now() - _newsLastLoaded < 300000) return; // throttle 5 min
    _newsLastLoaded = Date.now();
    const syms = positions.map(p => p.symbol);
    if (!syms.length) { $('newsStatus').textContent = '—'; return; }

    $('newsStatus').textContent = 'Loading...';
    try {
      const r = await fetch('/api/v1/news/feed?symbols='+encodeURIComponent(syms.join(',')));
      if (!r.ok) { $('newsStatus').textContent = 'Failed'; return; }
      const items = await r.json();
      $('newsStatus').textContent = 'Updated '+new Date().toLocaleTimeString();
      $('newsBody').innerHTML = _renderNewsItems(items);
    } catch(_) { $('newsStatus').textContent = 'Failed'; }
  }

  // Per-stock news loaded inside the drill panel when a position is opened
  async function loadDrillNews(sym) {
    const body = $('drillNewsBody');
    const status = $('drillNewsStatus');
    if (!body) return;
    body.innerHTML = '<div style="padding:12px 18px;color:var(--muted);font-size:12px;">Loading\u2026</div>';
    status.textContent = '';
    try {
      const r = await fetch('/api/v1/news/feed?symbols='+encodeURIComponent(sym));
      if (!r.ok) { body.innerHTML = ''; status.textContent = 'Failed'; return; }
      const items = await r.json();
      body.innerHTML = _renderNewsItems(items);
      status.textContent = items.length ? items.length + ' stories' : '';
    } catch(_) { body.innerHTML = ''; status.textContent = 'Failed'; }
  }

  // ── Portfolio Performance ──────────────────────────────────────
  async function loadPerformance(days) {
    if (days == null) days = activePerfDays;
    activePerfDays = days;

    // Highlight active period button
    document.querySelectorAll('.period-btn').forEach(b => {
      b.classList.toggle('period-active', +b.dataset.days === days);
    });

    $('perfStatus').textContent = 'Loading...';
    try {
      const r = await fetch('/api/v1/performance/history?days=' + days);
      if (!r.ok) {
        $('perfPlaceholder').style.display = 'block';
        $('perfPlaceholder').innerHTML = '<div style="color:var(--muted);font-size:13px;">Could not load performance data.</div>';
        $('perfChartWrap').style.display = 'none';
        $('perfStats').style.display = 'none';
        $('perfStatus').textContent = '';
        return;
      }
      const data = await r.json();

      if (data.collecting || !data.snapshots || data.snapshots.length < 2) {
        const first = data.snapshots && data.snapshots.length
          ? data.snapshots[0].date
          : 'today';
        $('perfPlaceholder').innerHTML =
          '<div style="margin-bottom:12px;opacity:.35;"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg></div>'
          + '<div style="font-weight:600;margin-bottom:6px;">Building your history</div>'
          + '<div style="color:var(--muted);font-size:13px;">Tracking started ' + first + '.<br>Come back tomorrow to see your equity curve.</div>';
        $('perfPlaceholder').style.display = 'block';
        $('perfChartWrap').style.display = 'none';
        $('perfStats').style.display = 'none';
        $('perfStatus').textContent = data.total_snapshots + ' day' + (data.total_snapshots !== 1 ? 's' : '') + ' recorded';
        return;
      }

      $('perfPlaceholder').style.display = 'none';
      $('perfChartWrap').style.display = 'block';
      $('perfStats').style.display = 'block';

      const snaps = data.snapshots;
      const bench = data.benchmark || [];
      const m = data.metrics;

      // Normalise to % return from first snapshot
      const base = snaps[0].portfolio_value;
      const labels = snaps.map(s => s.date);
      const portPct = snaps.map(s => +((s.portfolio_value / base - 1) * 100).toFixed(3));

      // Align SPY returns
      const spyByDate = {};
      bench.forEach(b => { if (b.spy_close) spyByDate[b.date] = b.spy_close; });
      const spyBase = spyByDate[labels[0]];
      const spyPct = labels.map(d => {
        const v = spyByDate[d];
        return (v && spyBase) ? +((v / spyBase - 1) * 100).toFixed(3) : null;
      });

      // Render chart
      const ctx = $('perfChart').getContext('2d');
      if (perfChartInst) perfChartInst.destroy();
      perfChartInst = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            {
              label: 'Portfolio',
              data: portPct,
              borderColor: '#3fb950',
              backgroundColor: 'rgba(63,185,80,0.08)',
              borderWidth: 2.5,
              pointRadius: 0,
              pointHoverRadius: 5,
              fill: true,
              tension: 0.3,
            },
            {
              label: 'SPY',
              data: spyPct,
              borderColor: '#58a6ff',
              backgroundColor: 'transparent',
              borderWidth: 1.5,
              borderDash: [4, 3],
              pointRadius: 0,
              pointHoverRadius: 4,
              fill: false,
              tension: 0.3,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { labels: { color: '#7d8590', boxWidth: 14, font: { size: 12 } } },
            tooltip: {
              callbacks: {
                label: ctx => {
                  const v = ctx.parsed.y;
                  const sign = v >= 0 ? '+' : '';
                  const cur = ctx.dataset.label === 'Portfolio' && snaps[ctx.dataIndex]
                    ? ' ($' + snaps[ctx.dataIndex].portfolio_value.toLocaleString('en-US', {maximumFractionDigits:0}) + ')'
                    : '';
                  return ctx.dataset.label + ': ' + sign + v.toFixed(2) + '%' + cur;
                },
              },
            },
          },
          scales: {
            x: {
              ticks: {
                color: '#7d8590',
                maxTicksLimit: 8,
                maxRotation: 0,
                callback: function(val, idx) {
                  const d = labels[idx];
                  return d ? d.slice(5) : '';  // MM-DD
                },
              },
              grid: { color: 'rgba(255,255,255,0.04)' },
            },
            y: {
              ticks: {
                color: '#7d8590',
                callback: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%',
              },
              grid: { color: 'rgba(255,255,255,0.04)' },
            },
          },
        },
      });

      // Stats grid
      const gc2 = v => v >= 0 ? 'var(--green)' : 'var(--red)';
      const pct = (v, decimals) => {
        if (v == null) return '—';
        const s = v >= 0 ? '+' : '';
        return '<span style="color:' + gc2(v) + '">' + s + v.toFixed(decimals != null ? decimals : 2) + '%</span>';
      };
      const neutral = v => v != null ? v.toFixed(2) : '—';

      const outperform = (m.total_return_pct != null && m.spy_return_pct != null)
        ? m.total_return_pct - m.spy_return_pct : null;

      $('perfStats').innerHTML = '<div class="perf-stat-grid">'
        + stat('Total Return',  pct(m.total_return_pct))
        + stat('vs SPY',        pct(outperform) + (m.spy_return_pct != null ? '<div class="sub-text">SPY ' + (m.spy_return_pct >= 0 ? '+' : '') + m.spy_return_pct.toFixed(2) + '%</div>' : ''))
        + stat('Sharpe Ratio',  neutral(m.sharpe))
        + stat('Max Drawdown',  pct(m.max_drawdown_pct))
        + stat('Volatility',    m.volatility_pct != null ? m.volatility_pct.toFixed(1) + '% ann.' : '—')
        + stat('Best Day',      pct(m.best_day_pct))
        + stat('Worst Day',     pct(m.worst_day_pct))
        + stat('Win Rate',      m.win_rate_pct != null ? m.win_rate_pct.toFixed(0) + '% days' : '—')
        + '</div>';

      $('perfStatus').textContent = snaps.length + ' trading days  ·  since ' + snaps[0].date;
    } catch(e) {
      $('perfPlaceholder').innerHTML = '<div style="color:var(--muted);font-size:13px;">Could not load performance data.</div>';
      $('perfStatus').textContent = '';
    }
  }

  function stat(label, valHtml) {
    return '<div class="perf-stat"><div class="perf-stat-label">' + label + '</div><div class="perf-stat-val">' + valHtml + '</div></div>';
  }

  // Animate a button's label with trailing dots while an async operation runs.
  // Returns a stop function; calling it sets the final label and re-enables the button.
  function _animBtn(btn, baseLabel, resetLabel, resetDelay) {
    btn.disabled = true;
    const frames = ['.', '..', '...'];
    let i = 0;
    btn.textContent = baseLabel + frames[i];
    const timer = setInterval(() => { i = (i+1) % frames.length; btn.textContent = baseLabel + frames[i]; }, 500);
    return (doneLabel) => {
      clearInterval(timer);
      btn.textContent = doneLabel || resetLabel;
      if (resetLabel) setTimeout(() => { btn.disabled = false; btn.textContent = resetLabel; }, resetDelay || 4000);
      else btn.disabled = false;
    };
  }

  // Full History: fetches real transaction history from Schwab and reconstructs
  // portfolio holdings at every historical date. Falls back to holdings estimate
  // automatically if no transactions are available.
  $('perfRebuildBtn').addEventListener('click', async () => {
    const btn = $('perfRebuildBtn');
    $('perfBackfillBtn').disabled = true;
    $('perfStatus').textContent = 'Fetching Schwab transactions \u2014 this may take 10\u201330 seconds\u2026';
    const stop = _animBtn(btn, 'Fetching history', '\u21bb Full History', 5000);
    try {
      const r = await fetch('/api/v1/performance/rebuild?years=10', { method: 'POST' });
      const d = await r.json();
      const method = d.method === 'transaction_reconstruction'
        ? d.transactions_used + ' txns \u2192 ' + d.inserted + ' days'
        : d.inserted + ' days (estimated)';
      stop(method);
      setTimeout(() => { $('perfBackfillBtn').disabled = false; }, 5000);
      loadPerformance(activePerfDays);
    } catch(e) {
      stop('Failed');
      setTimeout(() => { $('perfBackfillBtn').disabled = false; btn.disabled = false; btn.textContent = '\u21bb Full History'; }, 2000);
    }
  });

  // Quick Estimate: uses current holdings × past closes — good for a quick refresh
  $('perfBackfillBtn').addEventListener('click', async () => {
    const btn = $('perfBackfillBtn');
    const stop = _animBtn(btn, 'Estimating', '\u21bb Quick Estimate', 3000);
    try {
      const r = await fetch('/api/v1/performance/backfill?days=1825', { method: 'POST' });
      const d = await r.json();
      stop(d.inserted + ' days filled');
      loadPerformance(activePerfDays);
    } catch(e) {
      stop('Failed');
      setTimeout(() => { btn.disabled = false; btn.textContent = '\u21bb Quick Estimate'; }, 2000);
    }
  });

  // Period button clicks
  $('perfPeriods').addEventListener('click', e => {
    const btn = e.target.closest('.period-btn');
    if (btn) loadPerformance(+btn.dataset.days);
  });

  // ── Position drill-down ───────────────────────────────────────
  let drillChartInst = null;
  let activeDrillSym = null;

  const _mainEl = () => $('mainArea');
  const _pushW   = { drill: 456, chat: 396 };  // panel width + small gap

  function closeDrill() {
    $('drillPanel').classList.remove('open');
    _mainEl().style.paddingRight = '';
    activeDrillSym = null;
  }

  // ── Edge drag-to-resize ───────────────────────────────────────
  let _resize = null;

  function _initEdgeDrag(stripId, panelId, closeFunc) {
    $(stripId).addEventListener('mousedown', e => {
      e.preventDefault();
      const panel = $(panelId);
      _resize = { startX: e.clientX, startW: panel.offsetWidth, panel, closeFunc, moved: false };
      document.body.classList.add('is-resizing');
    });
  }

  _initEdgeDrag('drillCloseEdge', 'drillPanel', closeDrill);

  document.addEventListener('mousemove', e => {
    if (!_resize) return;
    const dx = _resize.startX - e.clientX; // drag left = wider
    if (Math.abs(dx) > 3) _resize.moved = true;
    const newW = Math.max(280, Math.min(800, _resize.startW + dx));
    _resize.panel.style.width = newW + 'px';
    if (window.innerWidth > 900) _mainEl().style.paddingRight = (newW + 16) + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!_resize) return;
    document.body.classList.remove('is-resizing');
    const { panel, closeFunc, moved } = _resize;
    _resize = null;
    if (!moved) { closeFunc(); return; }
    if (panel.offsetWidth < 220) { closeFunc(); panel.style.width = ''; }
  });

  function openDrill(pos) {
    // Close chat first (without its push — drill push will take over)
    if ($('chatPanel').classList.contains('open')) {
      $('chatPanel').classList.remove('open');
    }

    activeDrillSym = pos.symbol;
    $('drillSym').textContent = pos.symbol;
    $('drillCo').textContent = '';
    $('drillPrice').textContent = usd(pos.currentPrice);
    $('drillDay').innerHTML = span(gc(pos.dayPnl), usd(pos.dayPnl) + ' (' + pct(pos.dayPct) + ') today');

    renderDrillStats(pos);
    // Reset options section for new symbol
    $('drillOptionsWrap').style.display = 'none';
    $('drillOptionsWrap').innerHTML = '';
    $('drillOptionsBtn').textContent = '\u25bc Options Chain';
    $('drillOptionsBtn').disabled = false;

    if (window.innerWidth > 900) _mainEl().style.paddingRight = _pushW.drill + 'px';
    $('drillPanel').classList.add('open');

    const tab = document.querySelector('.period-tab.active');
    loadDrillChart(pos.symbol, pos.avgCost, tab.dataset.pt, +tab.dataset.p, tab.dataset.ft, +tab.dataset.f);
    loadDrillFundamentals(pos.symbol);
    loadDrillNews(pos.symbol);
    loadQuickTake(pos.symbol);
  }

  function renderDrillStats(pos) {
    const qtyFmt = pos.qty % 1 === 0 ? num(pos.qty, 0) : num(pos.qty, 4);
    $('drillStats').innerHTML = [
      ['Shares',    qtyFmt],
      ['Avg Cost',  usd(pos.avgCost)],
      ['Mkt Value', usd(pos.mktVal)],
      ['Cost Basis',usd(pos.costBasis)],
      ['Total P&L', span(gc(pos.totalPnl), usd(pos.totalPnl))],
      ['Return',    span(gc(pos.totalPct), pct(pos.totalPct))],
    ].map(([k, v]) =>
      '<div><div class="dstat-label">'+k+'</div><div class="dstat-val">'+v+'</div></div>'
    ).join('');
  }

  async function loadDrillChart(symbol, avgCost, periodType, period, frequencyType, frequency) {
    if (typeof Chart === 'undefined') return;
    try {
      const url = '/api/v1/schwab/pricehistory?symbol='+symbol
        +'&periodType='+periodType+'&period='+period
        +'&frequencyType='+frequencyType+'&frequency='+frequency;
      const r = await fetch(url);
      if (!r.ok) return;
      const data = await r.json();
      const candles = data.candles || [];
      if (!candles.length) return;

      const isIntraday = frequencyType === 'minute';
      const labels = candles.map(c => {
        const d = new Date(c.datetime);
        return isIntraday
          ? d.toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit'})
          : d.toLocaleDateString('en-US', {month:'short', day:'numeric'});
      });
      const closes = candles.map(c => c.close);
      const last = closes[closes.length - 1];
      const up = last >= avgCost;
      const lineColor = up ? '#3fb950' : '#f85149';
      const fillColor = up ? 'rgba(63,185,80,0.07)' : 'rgba(248,81,73,0.07)';

      if (drillChartInst) { drillChartInst.destroy(); drillChartInst = null; }
      drillChartInst = new Chart($('drillChart'), {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              data: closes, borderColor: lineColor, borderWidth: 2,
              pointRadius: 0, fill: true, backgroundColor: fillColor, tension: 0.2,
            },
            {
              data: Array(closes.length).fill(avgCost),
              borderColor: 'rgba(255,255,255,0.25)', borderWidth: 1,
              borderDash: [5, 4], pointRadius: 0, fill: false,
            },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              mode: 'index', intersect: false,
              callbacks: {
                label: ctx => ctx.datasetIndex === 0
                  ? ' Price: ' + usd(ctx.raw)
                  : ' Avg cost: ' + usd(ctx.raw),
              },
            },
          },
          scales: {
            x: { grid: { display: false }, ticks: { color: '#7d8590', font: {size:10}, maxTicksLimit: 7, maxRotation: 0 } },
            y: { position: 'right', grid: { color: 'rgba(255,255,255,0.05)' },
                 ticks: { color: '#7d8590', font: {size:10}, callback: v => '$'+v.toFixed(0) } },
          },
        },
      });
    } catch(_) {}
  }

  async function loadDrillFundamentals(symbol) {
    $('drillFund').innerHTML = '<div class="drill-overview-empty">Loading…</div>';
    try {
      const r = await fetch('/api/v1/earnings/fundamentals/'+symbol);
      if (!r.ok) { $('drillFund').innerHTML = ''; return; }
      const f = await r.json();
      if (f.error) { $('drillFund').innerHTML = ''; return; }
      if (f.company_name) $('drillCo').textContent = f.company_name;

      const fmtPct = v => v != null ? (v > 1 ? '+'+parseFloat(v).toFixed(1) : (parseFloat(v)*100).toFixed(1))+'%' : null;
      const consensus = f.recommendation ? f.recommendation.toUpperCase() : null;
      const conClass  = consensus
        ? (consensus.includes('BUY') ? 'consensus-buy' : consensus.includes('SELL') ? 'consensus-sell' : 'consensus-hold')
        : '';

      // ── Tags row ──
      let tagsHtml = '';
      if (f.sector && f.sector !== 'Unknown') tagsHtml += '<span class="thesis-tag">'+f.sector+'</span>';
      if (consensus) tagsHtml += '<span class="thesis-tag '+conClass+'">'+consensus+'</span>';

      // ── Analyst target row ──
      let targetHtml = '';
      if (f.analyst_target != null) {
        const tgt    = parseFloat(f.analyst_target);
        const price  = parseFloat($('drillPrice').textContent.replace(/[^0-9.]/g,'')) || 0;
        const upside = price > 0 ? ((tgt - price) / price * 100) : null;
        const upCol  = upside != null ? (upside >= 0 ? 'var(--green)' : 'var(--red)') : '';
        const upTxt  = upside != null ? (upside >= 0 ? '+' : '')+upside.toFixed(1)+'%' : '';
        targetHtml = '<div class="thesis-target">'
          + '<span class="thesis-target-label">Analyst Target</span>'
          + '<span class="thesis-target-price">$'+tgt.toFixed(2)+'</span>'
          + (upTxt ? '<span class="thesis-target-upside" style="color:'+upCol+'">'+upTxt+'</span>' : '')
          + '</div>';
      }

      // ── Metrics 2-col grid ──
      const metrics = [
        ['P / E',       f.pe_ratio    != null ? parseFloat(f.pe_ratio).toFixed(1)    : null],
        ['Fwd P / E',   f.forward_pe  != null ? parseFloat(f.forward_pe).toFixed(1)  : null],
        ['PEG',         f.peg_ratio   != null ? parseFloat(f.peg_ratio).toFixed(2)   : null],
        ['Rev Growth',  fmtPct(f.revenue_growth)],
        ['Margin',      fmtPct(f.profit_margin)],
        ['Earnings',    fmtPct(f.earnings_growth)],
      ].filter(([, v]) => v != null);

      const metricsHtml = metrics.length
        ? '<div class="thesis-metrics">'
          + metrics.map(([k, v]) => {
              const col = (k === 'Rev Growth' || k === 'Margin' || k === 'Earnings')
                ? (v.startsWith('-') ? ' style="color:var(--red);"' : ' style="color:var(--green);"')
                : '';
              return '<div class="thesis-metric">'
                + '<span class="thesis-metric-label">'+k+'</span>'
                + '<span class="thesis-metric-val"'+col+'>'+v+'</span>'
                + '</div>';
            }).join('')
          + '</div>'
        : '';

      // ── Stop levels ──
      const pos = positions.find(p => p.symbol === symbol);
      let stopHtml = '';
      if (pos && pos.currentPrice > 0) {
        const trailing8  = (pos.currentPrice * 0.92).toFixed(2);
        const trailing12 = (pos.currentPrice * 0.88).toFixed(2);
        const breakeven  = pos.avgCost.toFixed(2);
        const stopColor  = pos.currentPrice > pos.avgCost ? 'var(--green)' : 'var(--red)';
        stopHtml = '<div class="drill-overview-subhead">Stop Levels</div>'
          + '<div class="stop-strip">'
          + '<div class="stop-card"><div class="stop-card-label">Breakeven</div><div class="stop-card-value" style="color:'+stopColor+'">$'+breakeven+'</div></div>'
          + '<div class="stop-card"><div class="stop-card-label">8% Trailing Stop</div><div class="stop-card-value">$'+trailing8+'</div></div>'
          + '<div class="stop-card"><div class="stop-card-label">12% Trailing Stop</div><div class="stop-card-value">$'+trailing12+'</div></div>'
          + '</div>';
      }

      const hasContent = tagsHtml || targetHtml || metricsHtml || stopHtml;
      $('drillFund').innerHTML = hasContent
        ? (tagsHtml ? '<div class="thesis-tags">'+tagsHtml+'</div>' : '')
          + targetHtml
          + metricsHtml
          + stopHtml
        : '<div class="drill-overview-empty">No fundamentals available.</div>';
    } catch(_) { $('drillFund').innerHTML = '<div class="drill-overview-empty">Could not load fundamentals.</div>'; }
  }

  // Period tab switching
  $('periodTabs').addEventListener('click', e => {
    const tab = e.target.closest('.period-tab');
    if (!tab || !activeDrillSym) return;
    document.querySelectorAll('.period-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const pos = positions.find(p => p.symbol === activeDrillSym);
    if (pos) loadDrillChart(activeDrillSym, pos.avgCost, tab.dataset.pt, +tab.dataset.p, tab.dataset.ft, +tab.dataset.f);
  });

  // Click any position row to open drill-down (sell button takes priority)
  $('posBody').addEventListener('click', e => {
    const sellBtn = e.target.closest('.sell-pos-btn');
    if (sellBtn) { openSellModal(sellBtn.dataset.sym); return; }
    const row = e.target.closest('tr');
    if (!row || row.classList.contains('empty-row')) return;
    const sym = row.querySelector('.sym')?.textContent?.trim();
    const pos = positions.find(p => p.symbol === sym);
    if (pos) openDrill(pos);
  });

  // ── Portfolio charts ──────────────────────────────────────────
  const PALETTE = [
    '#388bfd','#3fb950','#a371f7','#ffa657',
    '#ff7b72','#ffd700','#56d364','#79c0ff',
    '#f78166','#b38ef3','#ffa198','#89dcff',
  ];

  let pnlChartInst = null;
  let bubbleChartInst = null;
  let waterfallChartInst = null;
  let scatterChartInst = null;

  // ── Treemap (pure CSS — no plugin needed) ────────────────────────
  function renderTreemap(posArr) {
    const wrap = $('treemapWrap');
    if (!wrap) return;
    const equity = posArr.filter(p => p.mktVal > 0);
    if (!equity.length) { wrap.innerHTML = ''; return; }

    const W = wrap.offsetWidth || 800;
    const H = wrap.offsetHeight || 220;
    const totalVal = equity.reduce((s, p) => s + p.mktVal, 0);

    // Normalize to pixel areas summing to W*H
    const nodes = [...equity]
      .sort((a, b) => b.mktVal - a.mktVal)
      .map(p => ({ p, area: (p.mktVal / totalVal) * W * H }));

    // Worst aspect ratio for a candidate row given current remaining bounds
    function worstRatio(row, s, dw, dh) {
      const side = Math.min(dw, dh);
      let max = 0;
      for (const n of row) {
        // ratio = max(side²*a/s², s²/(side²*a))
        const r = Math.max(side * side * n.area / (s * s), s * s / (side * side * n.area));
        if (r > max) max = r;
      }
      return max;
    }

    // Place one strip and return updated bounds
    function placeStrip(row, s, dx, dy, dw, dh, out) {
      if (dw >= dh) {
        // Vertical strip on left: items stacked top-to-bottom
        const stripW = s / dh;
        let ey = dy;
        for (const n of row) {
          const itemH = n.area / stripW;
          out.push({ n: n.p, x: dx, y: ey, w: stripW, h: itemH });
          ey += itemH;
        }
        return { dx: dx + stripW, dy, dw: dw - stripW, dh };
      } else {
        // Horizontal strip at top: items laid left-to-right
        const stripH = s / dw;
        let ex = dx;
        for (const n of row) {
          const itemW = n.area / stripH;
          out.push({ n: n.p, x: ex, y: dy, w: itemW, h: stripH });
          ex += itemW;
        }
        return { dx, dy: dy + stripH, dw, dh: dh - stripH };
      }
    }

    const rects = [];
    let row = [], s = 0;
    let dx = 0, dy = 0, dw = W, dh = H;

    for (const n of nodes) {
      const testRow = [...row, n];
      const testS = s + n.area;
      if (row.length === 0 || worstRatio(testRow, testS, dw, dh) <= worstRatio(row, s, dw, dh)) {
        row.push(n); s += n.area;
      } else {
        ({ dx, dy, dw, dh } = placeStrip(row, s, dx, dy, dw, dh, rects));
        row = [n]; s = n.area;
      }
    }
    if (row.length) placeStrip(row, s, dx, dy, dw, dh, rects);

    function pnlColor(pct) {
      if (pct >= 30) return ['#1a4731', '#3fb950'];
      if (pct >= 15) return ['#1a3d2a', '#2ea043'];
      if (pct >= 5)  return ['#153225', '#238636'];
      if (pct >= 0)  return ['#0f2619', '#1a7f37'];
      if (pct >= -5) return ['#3d1a1a', '#da3633'];
      if (pct >= -15)return ['#4a1414', '#f85149'];
      return ['#5a0e0e', '#ff7b72'];
    }

    const gap = 2;
    wrap.innerHTML = rects.map(({ n, x, y, w, h }) => {
      const [bg, border] = pnlColor(n.totalPct);
      const sign = n.totalPct >= 0 ? '+' : '';
      const showLabel = w > 36 && h > 24;
      const showSub   = w > 50 && h > 40;
      return `<div title="${n.symbol}: ${usd(n.mktVal)} | ${sign}${n.totalPct.toFixed(1)}%" style="
        position:absolute;left:${x+gap}px;top:${y+gap}px;width:${Math.max(w-gap*2,1)}px;height:${Math.max(h-gap*2,1)}px;
        background:${bg};border:1px solid ${border};border-radius:4px;overflow:hidden;
        display:flex;flex-direction:column;justify-content:center;align-items:center;
        cursor:default;transition:filter .15s;
      " onmouseover="this.style.filter='brightness(1.3)'" onmouseout="this.style.filter=''">
        ${showLabel ? `<div style="font-size:${Math.min(Math.floor(Math.min(w,h)/3.5),13)}px;font-weight:700;color:#e6edf3;line-height:1.1">${n.symbol}</div>` : ''}
        ${showSub   ? `<div style="font-size:${Math.min(Math.floor(Math.min(w,h)/5.5),10)}px;color:${n.totalPct>=0?'#3fb950':'#f85149'}">${sign}${n.totalPct.toFixed(1)}%</div>` : ''}
      </div>`;
    }).join('');
  }

  async function updateCharts(posArr) {
    if (!posArr || !posArr.length || typeof Chart === 'undefined') return;
    Chart.defaults.color = '#7d8590';
    Chart.defaults.font.family = 'ui-sans-serif, system-ui, -apple-system, sans-serif';

    const equity = posArr.filter(p => p.costBasis > 0);

    // ── 1. Treemap ──────────────────────────────────────────────────
    renderTreemap(equity);

    // ── 2. Bubble chart: weight % (x) vs total return % (y), size = mktVal ──
    const maxMkt = Math.max(...equity.map(p => p.mktVal), 1);
    if (bubbleChartInst) { bubbleChartInst.destroy(); bubbleChartInst = null; }
    bubbleChartInst = new Chart($('bubbleChart'), {
      type: 'bubble',
      data: {
        datasets: equity.map(p => ({
          label: p.symbol,
          data: [{ x: parseFloat(p.weight.toFixed(2)), y: parseFloat(p.totalPct.toFixed(2)), r: Math.max(Math.sqrt(p.mktVal / maxMkt) * 28, 5) }],
          backgroundColor: p.totalPct >= 0 ? 'rgba(63,185,80,0.55)' : 'rgba(248,81,73,0.55)',
          borderColor: p.totalPct >= 0 ? '#3fb950' : '#f85149',
          borderWidth: 1,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.x.toFixed(1)}% weight, ${ctx.parsed.y.toFixed(1)}% return` } },
        },
        scales: {
          x: { title: { display: true, text: 'Portfolio Weight %', color: '#7d8590', font: { size: 10 } },
               grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#7d8590', font: { size: 10 }, callback: v => v + '%' } },
          y: { title: { display: true, text: 'Total Return %', color: '#7d8590', font: { size: 10 } },
               grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#7d8590', font: { size: 10 }, callback: v => v + '%' } },
        },
      },
    });

    // ── 3. Waterfall: P&L attribution (floating bars) ───────────────
    const byPnlWf = [...equity].sort((a, b) => b.totalPnl - a.totalPnl);
    let running = 0;
    const wfData = byPnlWf.map(p => {
      const start = running;
      running += p.totalPnl;
      return { min: Math.min(start, running), max: Math.max(start, running), pnl: p.totalPnl };
    });
    if (waterfallChartInst) { waterfallChartInst.destroy(); waterfallChartInst = null; }
    waterfallChartInst = new Chart($('waterfallChart'), {
      type: 'bar',
      data: {
        labels: [...byPnlWf.map(p => p.symbol), 'TOTAL'],
        datasets: [{
          data: [...wfData.map(d => [d.min, d.max]), [0, running]],
          backgroundColor: [...byPnlWf.map(p => p.totalPnl >= 0 ? 'rgba(63,185,80,0.7)' : 'rgba(248,81,73,0.7)'), running >= 0 ? 'rgba(63,185,80,0.9)' : 'rgba(248,81,73,0.9)'],
          borderColor: [...byPnlWf.map(p => p.totalPnl >= 0 ? '#3fb950' : '#f85149'), running >= 0 ? '#3fb950' : '#f85149'],
          borderWidth: 1, borderRadius: 2,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => {
            const idx = ctx.dataIndex;
            const val = idx < byPnlWf.length ? byPnlWf[idx].totalPnl : running;
            return ' ' + (val >= 0 ? '+' : '') + usd(val);
          }}},
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#e6edf3', font: { size: 10, weight: '600' } } },
          y: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#7d8590', font: { size: 10 }, callback: v => '$' + (Math.abs(v) >= 1000 ? (v/1000).toFixed(1)+'k' : v) } },
        },
      },
    });

    // ── 4. Day vs All-Time grouped bars ────────────────────────────
    const byMkt = [...equity].sort((a, b) => b.mktVal - a.mktVal).slice(0, 12);
    if (pnlChartInst) { pnlChartInst.destroy(); pnlChartInst = null; }
    pnlChartInst = new Chart($('pnlChart'), {
      type: 'bar',
      data: {
        labels: byMkt.map(p => p.symbol),
        datasets: [
          {
            label: "Today's P&L",
            data: byMkt.map(p => parseFloat(p.dayPnl.toFixed(2))),
            backgroundColor: byMkt.map(p => p.dayPnl >= 0 ? 'rgba(63,185,80,0.8)' : 'rgba(248,81,73,0.8)'),
            borderColor: byMkt.map(p => p.dayPnl >= 0 ? '#3fb950' : '#f85149'),
            borderWidth: 1, borderRadius: 3,
          },
          {
            label: 'All-Time P&L',
            data: byMkt.map(p => parseFloat(p.totalPnl.toFixed(2))),
            backgroundColor: byMkt.map(p => p.totalPnl >= 0 ? 'rgba(56,139,253,0.55)' : 'rgba(248,81,73,0.35)'),
            borderColor: byMkt.map(p => p.totalPnl >= 0 ? '#388bfd' : '#f85149'),
            borderWidth: 1, borderRadius: 3,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: 'top', labels: { color: '#7d8590', font: { size: 10 }, boxWidth: 10, padding: 10 } },
          tooltip: { callbacks: { label: ctx => ' ' + ctx.dataset.label + ': ' + (ctx.raw >= 0 ? '+' : '') + usd(ctx.raw) } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#e6edf3', font: { size: 10, weight: '600' } } },
          y: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#7d8590', font: { size: 10 }, callback: v => '$' + (Math.abs(v) >= 1000 ? (v/1000).toFixed(1)+'k' : v) } },
        },
      },
    });

    // ── 5. Concentration risk scatter: weight % (x) vs return % (y) ──
    if (scatterChartInst) { scatterChartInst.destroy(); scatterChartInst = null; }
    scatterChartInst = new Chart($('scatterChart'), {
      type: 'scatter',
      data: {
        datasets: [{
          label: 'Positions',
          data: equity.map(p => ({ x: parseFloat(p.weight.toFixed(2)), y: parseFloat(p.totalPct.toFixed(2)), sym: p.symbol })),
          backgroundColor: equity.map(p => p.totalPct >= 0 ? 'rgba(63,185,80,0.7)' : 'rgba(248,81,73,0.7)'),
          borderColor: equity.map(p => p.totalPct >= 0 ? '#3fb950' : '#f85149'),
          borderWidth: 1, pointRadius: 6, pointHoverRadius: 8,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `${ctx.raw.sym}: ${ctx.parsed.x.toFixed(1)}% of portfolio, ${ctx.parsed.y.toFixed(1)}% return` } },
        },
        scales: {
          x: { title: { display: true, text: 'Portfolio Weight %', color: '#7d8590', font: { size: 10 } },
               grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#7d8590', font: { size: 10 }, callback: v => v + '%' },
               min: 0 },
          y: { title: { display: true, text: 'Total Return %', color: '#7d8590', font: { size: 10 } },
               grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#7d8590', font: { size: 10 }, callback: v => v + '%' } },
        },
      },
      plugins: [{
        id: 'symbolLabels',
        afterDatasetsDraw(chart) {
          const { ctx, data } = chart;
          ctx.save();
          ctx.font = '600 9px ui-sans-serif,system-ui,sans-serif';
          ctx.fillStyle = '#e6edf3';
          ctx.textAlign = 'center';
          data.datasets[0].data.forEach((pt, i) => {
            const meta = chart.getDatasetMeta(0);
            if (!meta.data[i]) return;
            const { x, y } = meta.data[i].getProps(['x','y']);
            ctx.fillText(pt.sym, x, y - 9);
          });
          ctx.restore();
        },
      }],
    });
  }

  // ── Earnings calendar ─────────────────────────────────────────
  async function loadEarnings() {
    try {
      const r = await fetch('/api/v1/earnings/calendar');
      if (!r.ok) return;
      const items = await r.json();
      $('earningsUpdated').textContent = 'Updated ' + new Date().toLocaleTimeString();

      if (!items.length) {
        $('earningsBody').innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted);font-size:13px;">No upcoming earnings found for held symbols.</div>';
        return;
      }

      $('earningsBody').innerHTML = items.map(e => {
        const d = e.days_until;
        const label = d === 0 ? 'TODAY' : d === 1 ? 'TOMORROW' : d < 0 ? Math.abs(d) + 'd ago' : 'in ' + d + 'd';
        const cls = e.is_urgent ? 'badge-urgent' : e.is_soon ? 'badge-soon' : 'badge-normal';
        return '<div class="earn-row">'
          + '<span class="earn-sym">'+e.symbol+'</span>'
          + '<span class="earn-date">'+e.date+'</span>'
          + '<span class="earn-badge '+cls+'">'+label+'</span>'
          + '<button class="brief-btn" data-sym="'+e.symbol+'" data-date="'+e.date+'" data-days="'+d+'">AI Brief</button>'
          + '</div>';
      }).join('');
    } catch(err) {
      $('earningsBody').innerHTML = '<div style="padding:16px;color:var(--muted);font-size:13px;">Could not load earnings calendar.</div>';
    }
  }

  function closeBrief() {
    $('briefOverlay').style.display = 'none';
    $('briefContent').textContent = '';
  }

  async function openBrief(symbol, earningsDate, daysUntil) {
    $('briefTitle').textContent = symbol + ' — Pre-Earnings Brief (' + earningsDate + ')';
    $('briefContent').textContent = 'Generating brief...';
    $('briefOverlay').style.display = 'flex';

    let text = '';
    try {
      const resp = await fetch('/api/v1/earnings/brief/' + symbol);
      if (!resp.ok) { const e = await resp.json(); throw new Error(e.detail || 'Failed'); }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      $('briefContent').textContent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const line of decoder.decode(value).split('\\n')) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6);
          if (data === '[DONE]') break;
          try {
            const obj = JSON.parse(data);
            if (obj.text) { text += obj.text; $('briefContent').textContent = text; }
            if (obj.error) throw new Error(obj.error);
          } catch(pe) { if (pe.message !== 'Unexpected end of JSON input') throw pe; }
        }
      }
    } catch(e) {
      $('briefContent').textContent = 'Error: ' + e.message;
    }
  }

  $('briefOverlay').addEventListener('click', e => { if (e.target === $('briefOverlay')) closeBrief(); });
  $('earningsBody').addEventListener('click', e => {
    const btn = e.target.closest('.brief-btn');
    if (!btn) return;
    openBrief(btn.dataset.sym, btn.dataset.date, parseInt(btn.dataset.days));
  });

  loadEarnings();
  setInterval(loadEarnings, 300000); // refresh every 5 min

  // ── Options Chain drill-down ──────────────────────────────────
  let _optCallMap = {}, _optPutMap = {}, _optUnderlying = 0;

  $('drillOptionsBtn').addEventListener('click', () => {
    const wrap = $('drillOptionsWrap');
    if (wrap.style.display === 'block') {
      wrap.style.display = 'none';
      $('drillOptionsBtn').textContent = '\u25bc Options Chain';
    } else {
      loadDrillOptions();
    }
  });

  async function loadDrillOptions() {
    const sym = activeDrillSym;
    if (!sym) return;
    const btn = $('drillOptionsBtn');
    const wrap = $('drillOptionsWrap');
    btn.textContent = 'Loading...';
    btn.disabled = true;
    try {
      const r = await fetch('/api/v1/schwab/options-chain?symbol='+sym+'&strikeCount=12');
      if (!r.ok) throw new Error('Options unavailable ('+r.status+')');
      const data = await r.json();

      _optUnderlying = data.underlyingPrice || data.underlying?.last || 0;
      _optCallMap = data.callExpDateMap || {};
      _optPutMap  = data.putExpDateMap  || {};

      const expiries = Object.keys(_optCallMap).sort();
      if (!expiries.length) {
        wrap.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px 0;">No options data available.</div>';
      } else {
        const tabsHtml = '<div id="optExpTabs" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px;">'
          + expiries.slice(0, 4).map((exp, i) => {
              const label = exp.split(':')[0];
              return '<button class="period-tab'+(i===0?' active':'')+'" data-exp="'+exp+'">'+label+'</button>';
            }).join('')
          + '</div>';
        wrap.innerHTML = tabsHtml + '<div id="optTableWrap"></div>';

        wrap.querySelector('#optExpTabs').addEventListener('click', e => {
          const tab = e.target.closest('[data-exp]');
          if (!tab) return;
          wrap.querySelectorAll('.period-tab').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
          renderOptionsTable(tab.dataset.exp);
        });

        renderOptionsTable(expiries[0]);
      }
      wrap.style.display = 'block';
      btn.textContent = '\u25b2 Options Chain';
    } catch(e) {
      wrap.innerHTML = '<div style="color:var(--red);font-size:12px;padding:8px 0;">'+e.message+'</div>';
      wrap.style.display = 'block';
      btn.textContent = '\u25bc Options Chain';
    } finally {
      btn.disabled = false;
    }
  }

  function renderOptionsTable(expiry) {
    const calls = _optCallMap[expiry] || {};
    const puts  = _optPutMap[expiry]  || {};
    const strikes = [...new Set([...Object.keys(calls), ...Object.keys(puts)])]
      .sort((a, b) => parseFloat(a) - parseFloat(b));
    const wrap = document.getElementById('optTableWrap');
    if (!wrap) return;
    if (!strikes.length) {
      wrap.innerHTML = '<div style="color:var(--muted);font-size:12px;">No strikes available.</div>';
      return;
    }
    const f = (v, d) => (v != null && !isNaN(v)) ? parseFloat(v).toFixed(d != null ? d : 2) : '\u2014';
    const ivFmt = v => (v != null && !isNaN(v)) ? (parseFloat(v)*100).toFixed(1)+'%' : '\u2014';
    wrap.innerHTML = '<div style="font-size:11px;color:var(--muted);margin-bottom:6px;">Underlying: $'+(_optUnderlying||0).toFixed(2)+'</div>'
      + '<table style="font-size:11px;min-width:480px;">'
      + '<thead><tr>'
      + '<th style="text-align:left;color:var(--green);padding:5px 6px">CALL Bid/Ask</th>'
      + '<th style="text-align:right;padding:5px 4px">\u0394</th>'
      + '<th style="text-align:right;padding:5px 4px">IV</th>'
      + '<th style="text-align:right;padding:5px 4px">OI</th>'
      + '<th style="text-align:center;padding:5px 8px;font-weight:800">Strike</th>'
      + '<th style="text-align:left;padding:5px 4px">OI</th>'
      + '<th style="text-align:left;padding:5px 4px">IV</th>'
      + '<th style="text-align:left;padding:5px 4px">\u0394</th>'
      + '<th style="text-align:right;color:var(--red);padding:5px 6px">PUT Bid/Ask</th>'
      + '</tr></thead>'
      + '<tbody>' + strikes.map(strike => {
          const c = (calls[strike] || [[]])[0] || {};
          const p = (puts[strike]  || [[]])[0] || {};
          const atm = _optUnderlying > 0 && Math.abs(parseFloat(strike) - _optUnderlying) / _optUnderlying < 0.015;
          const bg = atm ? 'background:rgba(63,185,80,0.08);' : '';
          return '<tr style="'+bg+'">'
            + '<td style="color:var(--green);padding:5px 6px">'+f(c.bid)+'/'+f(c.ask)+'</td>'
            + '<td style="text-align:right;padding:5px 4px">'+f(c.delta,3)+'</td>'
            + '<td style="text-align:right;padding:5px 4px">'+ivFmt(c.volatility)+'</td>'
            + '<td style="text-align:right;padding:5px 4px;color:var(--muted)">'+(c.openInterest!=null?c.openInterest:'\u2014')+'</td>'
            + '<td style="text-align:center;font-weight:800;padding:5px 8px'+(atm?';color:var(--green)':'')+'">'
              + strike + (atm ? ' <span style="font-size:10px;color:var(--green)">ATM</span>' : '') + '</td>'
            + '<td style="padding:5px 4px;color:var(--muted)">'+(p.openInterest!=null?p.openInterest:'\u2014')+'</td>'
            + '<td style="padding:5px 4px">'+ivFmt(p.volatility)+'</td>'
            + '<td style="padding:5px 4px">'+f(p.delta,3)+'</td>'
            + '<td style="text-align:right;color:var(--red);padding:5px 6px">'+f(p.bid)+'/'+f(p.ask)+'</td>'
            + '</tr>';
        }).join('')
      + '</tbody></table>';
  }

  // ── Advisor chat ──────────────────────────────────────────────
  let chatHistory = [];
  let chatStreaming = false;

  _initEdgeDrag('chatCloseEdge', 'chatPanel', () => toggleChat(false));

  function toggleChat(open) {
    const panel = $('chatPanel');
    const willOpen = open !== undefined ? open : !panel.classList.contains('open');
    if (willOpen) {
      // Close drill panel if open (its push will be replaced by chat push)
      if ($('drillPanel').classList.contains('open')) {
        $('drillPanel').classList.remove('open');
      }
      panel.classList.add('open');
      if (window.innerWidth > 900) _mainEl().style.paddingRight = _pushW.chat + 'px';
    } else {
      panel.classList.remove('open');
      _mainEl().style.paddingRight = '';
    }
  }

  document.getElementById('chatInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !chatStreaming) { e.preventDefault(); sendMessage(); }
  });

  document.getElementById('chatInput').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  });

  const _toolLabel = {
    get_portfolio:         'Fetching portfolio',
    get_price_history:     'Fetching price history',
    get_news:              'Fetching news',
    get_earnings_calendar: 'Fetching earnings data',
  };

  function appendMessage(role, text) {
    const msgs = document.getElementById('chatMessages');
    const div = document.createElement('div');
    div.className = 'msg msg-' + role;
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    if (role === 'assistant' && text) {
      bubble.innerHTML = _renderMd(text);
    } else {
      bubble.textContent = text;
    }
    div.appendChild(bubble);
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return bubble;
  }

  function _makeThinkingBubble(label) {
    const msgs = document.getElementById('chatMessages');
    const div = document.createElement('div');
    div.className = 'msg msg-assistant';
    div.id = 'thinkingMsg';
    div.innerHTML =
      '<div class="thinking-wrap">' +
        '<div class="think-dots"><span></span><span></span><span></span></div>' +
        '<span class="think-label" id="thinkLabel">' + label + '</span>' +
      '</div>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  function _removeThinkingBubble() {
    const el = document.getElementById('thinkingMsg');
    if (el) el.remove();
  }

  async function sendMessage() {
    if (chatStreaming) return;
    const input = document.getElementById('chatInput');
    const msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    input.style.height = 'auto';
    document.getElementById('chatSend').disabled = true;
    chatStreaming = true;

    appendMessage('user', msg);
    chatHistory.push({ role: 'user', content: msg });

    // Show initial thinking indicator
    _makeThinkingBubble('Thinking\u2026');

    let bubble = null;
    let fullText = '';

    try {
      const resp = await fetch('/api/v1/advisor/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, history: chatHistory.slice(0, -1) }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Request failed');
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const line of decoder.decode(value).split('\\n')) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6);
          if (data === '[DONE]') break;
          try {
            const obj = JSON.parse(data);

            if (obj.status === 'thinking' && obj.tools) {
              // Update thinking bubble label with tool names
              const labels = obj.tools.map(t => _toolLabel[t] || t).join(', ');
              const lbl = document.getElementById('thinkLabel');
              if (lbl) lbl.textContent = labels + '\u2026';
            } else if (obj.text) {
              // First text chunk — swap thinking bubble for real response bubble
              if (!bubble) {
                _removeThinkingBubble();
                bubble = appendMessage('assistant', '');
              }
              fullText += obj.text;
              bubble.innerHTML = _renderMd(fullText);
              document.getElementById('chatMessages').scrollTop = 99999;
            }
            if (obj.error) throw new Error(obj.error);
          } catch(pe) { if (pe.message !== 'Unexpected end of JSON input') throw pe; }
        }
      }
      _removeThinkingBubble();
      if (!bubble) bubble = appendMessage('assistant', '(no response)');
      chatHistory.push({ role: 'assistant', content: fullText });
      autoRunCodeBlocks(bubble);
    } catch(e) {
      _removeThinkingBubble();
      if (!bubble) bubble = appendMessage('assistant', '');
      const errMsg = e.message || '';
      if (errMsg.toLowerCase().includes('connection') || errMsg.toLowerCase().includes('network') || errMsg.toLowerCase().includes('failed to fetch')) {
        bubble.textContent = 'Could not reach the advisor. Check your connection and try again.';
      } else {
        bubble.textContent = 'Advisor error: ' + errMsg;
      }
    } finally {
      chatStreaming = false;
      document.getElementById('chatSend').disabled = false;
    }
  }
</script>
</body>
</html>"""
