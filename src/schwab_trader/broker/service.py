"""Broker service that manages token refresh and read-only Schwab access."""

from collections.abc import Callable, Mapping, Sequence

from schwab_trader.auth.models import OAuthToken
from schwab_trader.auth.service import SchwabOAuthService
from schwab_trader.auth.token_store import FileTokenStore
from schwab_trader.schwab.client import SchwabClient


class SchwabBrokerService:
    """Coordinate token state and Schwab API reads."""

    def __init__(
        self,
        *,
        token_store: FileTokenStore,
        oauth_service: SchwabOAuthService,
        client_factory: Callable[[str], object] = SchwabClient,
    ) -> None:
        self._token_store = token_store
        self._oauth_service = oauth_service
        self._client_factory = client_factory

    def get_account_numbers(self) -> list[dict]:
        return self._call(lambda client: client.get_account_numbers())

    def get_accounts(self, *, fields: Sequence[str] | None = None) -> list[dict]:
        return self._call(lambda client: client.get_accounts(fields=fields))

    def get_account(self, account_hash: str, *, fields: Sequence[str] | None = None) -> dict:
        return self._call(lambda client: client.get_account(account_hash, fields=fields))

    def get_orders_for_account(
        self,
        *,
        account_hash: str,
        from_entered_time: str,
        to_entered_time: str,
        max_results: int | None = None,
        status: str | None = None,
    ) -> list[dict]:
        return self._call(
            lambda client: client.get_orders_for_account(
                account_hash=account_hash,
                from_entered_time=from_entered_time,
                to_entered_time=to_entered_time,
                max_results=max_results,
                status=status,
            )
        )

    def get_all_orders(
        self,
        *,
        from_entered_time: str,
        to_entered_time: str,
        max_results: int | None = None,
        status: str | None = None,
    ) -> list[dict]:
        return self._call(
            lambda client: client.get_all_orders(
                from_entered_time=from_entered_time,
                to_entered_time=to_entered_time,
                max_results=max_results,
                status=status,
            )
        )

    def get_transactions(
        self,
        *,
        account_hash: str,
        start_date: str,
        end_date: str,
        types: Sequence[str],
        symbol: str | None = None,
    ) -> list[dict]:
        return self._call(
            lambda client: client.get_transactions(
                account_hash=account_hash,
                start_date=start_date,
                end_date=end_date,
                types=types,
                symbol=symbol,
            )
        )

    def get_transaction(self, account_hash: str, transaction_id: int) -> list[dict]:
        return self._call(lambda client: client.get_transaction(account_hash, transaction_id))

    def get_user_preferences(self) -> list[dict]:
        return self._call(lambda client: client.get_user_preferences())

    def get_quotes(self, symbols: Sequence[str], *, fields: Sequence[str] | None = None) -> dict:
        return self._call(lambda client: client.get_quotes(symbols, fields=fields))

    def get_market_hours(self, markets: Sequence[str], *, date: str | None = None) -> dict:
        return self._call(lambda client: client.get_market_hours(markets, date=date))

    def get_price_history(
        self,
        symbol: str,
        *,
        period_type: str = "month",
        period: int = 1,
        frequency_type: str = "daily",
        frequency: int = 1,
        need_extended_hours_data: bool = False,
    ) -> dict:
        return self._call(
            lambda client: client.get_price_history(
                symbol,
                period_type=period_type,
                period=period,
                frequency_type=frequency_type,
                frequency=frequency,
                need_extended_hours_data=need_extended_hours_data,
            )
        )

    def preview_order(self, *, account_hash: str, order_payload: Mapping[str, object]) -> dict:
        return self._call(lambda client: client.preview_order(account_hash, order_payload))

    def place_order(self, *, account_hash: str, order_payload: Mapping[str, object]) -> None:
        return self._call(lambda client: client.place_order(account_hash, order_payload))

    def get_primary_account_hash(self) -> str:
        """Return the hash of the first linked account."""
        numbers = self._call(lambda client: client.get_account_numbers())
        if not numbers:
            raise ValueError("No linked accounts found")
        return numbers[0]["hashValue"]

    def get_options_chain(
        self,
        symbol: str,
        *,
        contract_type: str = "ALL",
        strike_count: int = 10,
    ) -> dict:
        return self._call(
            lambda client: client.get_options_chain(
                symbol,
                contract_type=contract_type,
                strike_count=strike_count,
            )
        )

    def get_access_token(self) -> str:
        """Return a valid (auto-refreshed) access token string."""
        return self._get_active_token().access_token

    def token_status(self) -> dict[str, object]:
        """Return the current local auth status."""

        token = self._token_store.load()
        if token is None:
            return {"authenticated": False, "access_token_expires_at": None}
        return {
            "authenticated": True,
            "access_token_expires_at": token.access_token_expires_at,
        }

    def _call(self, operation):
        token = self._get_active_token()
        client = self._client_factory(token.access_token)
        try:
            return operation(client)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _get_active_token(self) -> OAuthToken:
        token = self._token_store.load()
        if token is None:
            raise RuntimeError("No Schwab token is stored. Complete OAuth authorization first.")
        if token.is_access_token_expired():
            if not token.refresh_token:
                raise RuntimeError("Stored Schwab token cannot be refreshed. Re-authorize first.")
            token = self._oauth_service.refresh_access_token(token.refresh_token)
            self._token_store.save(token)
        return token
