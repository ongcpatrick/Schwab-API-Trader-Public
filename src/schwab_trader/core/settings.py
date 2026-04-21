"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "schwab-api-trader"
    environment: str = "development"

    schwab_app_key: str | None = None
    schwab_app_secret: str | None = None
    schwab_callback_url: str | None = None
    schwab_scope: str = "readonly"
    schwab_token_path: Path = Field(default=Path("./.data/schwab-token.json"))
    journal_database_url: str = "sqlite:///./.data/journal.db"
    anthropic_api_key: str = ""
    quiver_quant_api_key: str = ""  # free tier at quiverquant.com — congressional trading data
    fred_api_key: str = ""          # free at https://fred.stlouisfed.org/docs/api/api_key.html

    # Twilio SMS alerts
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""   # e.g. +15551234567
    alert_phone_number: str = ""   # your mobile number

    # Dashboard URL sent in SMS (defaults to local network IP auto-detected at runtime)
    dashboard_url: str = ""

    # Agent monitoring thresholds
    agent_check_interval_minutes: int = 30
    alert_earnings_days: int = 3
    alert_position_down_pct: float = 8.0
    alert_day_loss_pct: float = 5.0
    alert_concentration_pct: float = 25.0
    alert_gain_pct: float = 30.0

    # Email notifications (smtplib — no extra dependencies)
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_smtp_user: str = ""
    email_smtp_password: str = ""
    alert_email_address: str = ""   # recipient

    # Buy-scan agent
    buy_scan_budget: float = 2000.0
    buy_scan_interval_hours: float = 24.0
    buy_scan_max_proposals: int = 3
    # Comma-separated list of tickers to scan for buy ideas.
    # Change this to any stocks that fit your investment style.
    buy_scan_watchlist: str = (
        "NVDA,AMD,TSM,AVGO,QCOM,MU,AMAT,KLAC,LRCX,ASML,MRVL,TXN,ADI,ON,SWKS,"
        "MSFT,GOOG,META,AMZN,ORCL,"
        "PLTR,CRWD,APP,NET,DDOG,ZS,COIN,TTD,MNDY,SNOW,"
        "TSLA,RIVN,"
        "SMH,SOXX,QQQ,ARKK,XLK,SOXQ,IGV"
    )
    # Minimum analyst upside % a proposal must have to trigger an email notification.
    # Proposals below this threshold still save to .alerts.json — they just don't email you.
    # Set to 0 to receive emails for every scan result.
    email_min_upside_pct: float = 15.0

    # Live execution guardrails
    live_order_kill_switch: bool = False
    live_order_max_daily_loss_dollars: float | None = None
    live_order_max_open_positions: int | None = None
    live_order_max_order_notional_dollars: float | None = None
    live_order_max_single_trade_risk_dollars: float | None = None
    live_order_max_symbol_allocation_pct: float | None = None
    live_order_require_stop_loss_for_entries: bool = False

    # Regime detection gate
    regime_enabled: bool = True

    @field_validator(
        "live_order_max_daily_loss_dollars",
        "live_order_max_open_positions",
        "live_order_max_order_notional_dollars",
        "live_order_max_single_trade_risk_dollars",
        "live_order_max_symbol_allocation_pct",
        mode="before",
    )
    @classmethod
    def _coerce_empty_to_none(cls, v: object) -> object:
        """Treat empty string or literal 'None' as None so optional numeric env vars work correctly."""
        if isinstance(v, str) and v.strip() in ("", "None", "null"):
            return None
        return v

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[3] / ".env"),
        env_file_encoding="utf-8",
        env_prefix="SCHWAB_TRADER_",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings for the current process."""

    return Settings()
