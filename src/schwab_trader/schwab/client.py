"""Thin REST client for Schwab trader and market-data APIs."""

from collections.abc import Mapping, Sequence
from urllib.parse import urlencode

import httpx


class SchwabClient:
    """Minimal Schwab REST client for safe, explicit API calls."""

    def __init__(
        self,
        access_token: str,
        *,
        trader_base_url: str = "https://api.schwabapi.com/trader/v1",
        market_data_base_url: str = "https://api.schwabapi.com/marketdata/v1",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._trader_base_url = trader_base_url.rstrip("/")
        self._market_data_base_url = market_data_base_url.rstrip("/")
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._client.close()

    def get_account_numbers(self) -> list[dict]:
        """Return linked accounts and their encrypted hash values."""

        return self._request("GET", f"{self._trader_base_url}/accounts/accountNumbers")

    def get_accounts(self, *, fields: Sequence[str] | None = None) -> list[dict]:
        """Return account balances and optional field expansions."""

        params = {"fields": ",".join(fields)} if fields else None
        return self._request("GET", f"{self._trader_base_url}/accounts", params=params)

    def get_account(self, account_hash: str, *, fields: Sequence[str] | None = None) -> dict:
        """Return a specific account by encrypted account hash."""

        params = {"fields": ",".join(fields)} if fields else None
        return self._request(
            "GET",
            f"{self._trader_base_url}/accounts/{account_hash}",
            params=params,
        )

    def get_quotes(
        self,
        symbols: Sequence[str],
        *,
        fields: Sequence[str] | None = None,
    ) -> dict:
        """Return quotes for one or more symbols."""

        params: dict[str, str] = {"symbols": ",".join(symbols)}
        if fields:
            params["fields"] = ",".join(fields)
        return self._request("GET", f"{self._market_data_base_url}/quotes", params=params)

    def get_market_hours(
        self,
        markets: Sequence[str],
        *,
        date: str | None = None,
    ) -> dict:
        """Return market hours for one or more market types."""

        params: dict[str, str] = {"markets": ",".join(markets)}
        if date:
            params["date"] = date
        return self._request("GET", f"{self._market_data_base_url}/markets", params=params)

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
        """Return OHLCV candles for a symbol."""

        params: dict[str, str] = {
            "symbol": symbol,
            "periodType": period_type,
            "period": str(period),
            "frequencyType": frequency_type,
            "frequency": str(frequency),
            "needExtendedHoursData": str(need_extended_hours_data).lower(),
        }
        return self._request("GET", f"{self._market_data_base_url}/pricehistory", params=params)

    def preview_order(self, account_hash: str, order_payload: Mapping[str, object]) -> dict:
        """Validate an order without placing it."""

        url = f"{self._trader_base_url}/accounts/{account_hash}/previewOrder"
        return self._request("POST", url, json=dict(order_payload))

    def place_order(self, account_hash: str, order_payload: Mapping[str, object]) -> None:
        """Place a live order. Returns None on success (Schwab returns 201 no body)."""

        url = f"{self._trader_base_url}/accounts/{account_hash}/orders"
        response = self._client.request(
            "POST", url,
            json=dict(order_payload),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

    def get_orders_for_account(
        self,
        *,
        account_hash: str,
        from_entered_time: str,
        to_entered_time: str,
        max_results: int | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """Return orders for a specific account."""

        params: dict[str, str] = {
            "fromEnteredTime": from_entered_time,
            "toEnteredTime": to_entered_time,
        }
        if max_results is not None:
            params["maxResults"] = str(max_results)
        if status:
            params["status"] = status
        url = f"{self._trader_base_url}/accounts/{account_hash}/orders"
        return self._request("GET", url, params=params)

    def get_all_orders(
        self,
        *,
        from_entered_time: str,
        to_entered_time: str,
        max_results: int | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """Return orders across all linked accounts."""

        params: dict[str, str] = {
            "fromEnteredTime": from_entered_time,
            "toEnteredTime": to_entered_time,
        }
        if max_results is not None:
            params["maxResults"] = str(max_results)
        if status:
            params["status"] = status
        return self._request("GET", f"{self._trader_base_url}/orders", params=params)

    def get_transactions(
        self,
        *,
        account_hash: str,
        start_date: str,
        end_date: str,
        types: Sequence[str],
        symbol: str | None = None,
    ) -> list[dict]:
        """Return transactions for a specific account."""

        params: dict[str, str] = {
            "startDate": start_date,
            "endDate": end_date,
            "types": ",".join(types),
        }
        if symbol:
            params["symbol"] = symbol
        url = f"{self._trader_base_url}/accounts/{account_hash}/transactions"
        return self._request("GET", url, params=params)

    def get_transaction(self, account_hash: str, transaction_id: int) -> list[dict]:
        """Return a specific transaction for an account."""

        url = f"{self._trader_base_url}/accounts/{account_hash}/transactions/{transaction_id}"
        return self._request("GET", url)

    def get_options_chain(
        self,
        symbol: str,
        *,
        contract_type: str = "ALL",
        strike_count: int = 10,
        include_underlying_quote: bool = True,
    ) -> dict:
        """Return the full options chain for a symbol."""

        params: dict[str, str] = {
            "symbol": symbol,
            "contractType": contract_type,
            "strikeCount": str(strike_count),
            "includeUnderlyingQuote": str(include_underlying_quote).lower(),
        }
        return self._request("GET", f"{self._market_data_base_url}/chains", params=params)

    def get_user_preferences(self) -> list[dict]:
        """Return the account and streaming preferences for the authenticated user."""

        return self._request("GET", f"{self._trader_base_url}/userPreference")

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, object] | None = None,
    ) -> dict | list[dict]:
        """Execute an HTTP request and return decoded JSON."""

        request_url = url
        if params:
            request_url = f"{url}?{urlencode(params)}"

        extra_headers = {"Content-Type": "application/json"} if json is not None else {}
        response = self._client.request(method, request_url, json=json, headers=extra_headers)
        response.raise_for_status()
        return response.json()
