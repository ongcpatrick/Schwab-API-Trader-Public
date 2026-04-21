import httpx

from schwab_trader.schwab.client import SchwabClient


def test_get_account_numbers_uses_trader_api_and_bearer_token() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        return httpx.Response(
            status_code=200,
            json=[{"accountNumber": "12345678", "hashValue": "abc123"}],
        )

    client = SchwabClient(
        access_token="token-123",
        transport=httpx.MockTransport(handler),
    )

    payload = client.get_account_numbers()

    assert captured["url"] == "https://api.schwabapi.com/trader/v1/accounts/accountNumbers"
    assert captured["auth"] == "Bearer token-123"
    assert payload == [{"accountNumber": "12345678", "hashValue": "abc123"}]


def test_get_quotes_joins_symbols_and_uses_market_data_api() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(status_code=200, json={"AAPL": {"quote": {"lastPrice": 189.5}}})

    client = SchwabClient(
        access_token="token-123",
        transport=httpx.MockTransport(handler),
    )

    payload = client.get_quotes(["AAPL", "MSFT"], fields=["quote", "regular"])

    assert (
        captured["url"]
        == "https://api.schwabapi.com/marketdata/v1/quotes?symbols=AAPL%2CMSFT&fields=quote%2Cregular"
    )
    assert payload == {"AAPL": {"quote": {"lastPrice": 189.5}}}


def test_preview_order_posts_payload_to_hashed_account_endpoint() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content.decode()
        return httpx.Response(status_code=200, json={"orderValidationResult": {}})

    client = SchwabClient(
        access_token="token-123",
        transport=httpx.MockTransport(handler),
    )

    payload = client.preview_order(
        account_hash="abc123",
        order_payload={
            "orderType": "LIMIT",
            "price": "189.50",
        },
    )

    assert captured["url"] == "https://api.schwabapi.com/trader/v1/accounts/abc123/previewOrder"
    assert captured["method"] == "POST"
    assert '"orderType":"LIMIT"' in captured["body"]
    assert payload == {"orderValidationResult": {}}


def test_get_account_uses_encrypted_account_id_and_positions_field() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(status_code=200, json={"securitiesAccount": {"accountNumber": "..."}})

    client = SchwabClient(
        access_token="token-123",
        transport=httpx.MockTransport(handler),
    )

    payload = client.get_account("abc123", fields=["positions"])

    assert captured["url"] == "https://api.schwabapi.com/trader/v1/accounts/abc123?fields=positions"
    assert payload == {"securitiesAccount": {"accountNumber": "..."}}


def test_get_orders_for_account_uses_required_entered_time_filters() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(status_code=200, json=[{"orderId": 123}])

    client = SchwabClient(
        access_token="token-123",
        transport=httpx.MockTransport(handler),
    )

    payload = client.get_orders_for_account(
        account_hash="abc123",
        from_entered_time="2026-03-29T00:00:00.000Z",
        to_entered_time="2026-04-14T23:59:59.000Z",
        max_results=100,
        status="FILLED",
    )

    assert (
        captured["url"]
        == "https://api.schwabapi.com/trader/v1/accounts/abc123/orders"
        "?fromEnteredTime=2026-03-29T00%3A00%3A00.000Z&toEnteredTime=2026-04-14T23%3A59%3A59.000Z"
        "&maxResults=100&status=FILLED"
    )
    assert payload == [{"orderId": 123}]


def test_get_transactions_uses_start_end_and_types() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(status_code=200, json=[{"activityId": 1}])

    client = SchwabClient(
        access_token="token-123",
        transport=httpx.MockTransport(handler),
    )

    payload = client.get_transactions(
        account_hash="abc123",
        start_date="2026-03-28T21:10:42.000Z",
        end_date="2026-04-14T21:10:42.000Z",
        types=["TRADE", "DIVIDEND_OR_INTEREST"],
        symbol="AAPL",
    )

    assert (
        captured["url"]
        == "https://api.schwabapi.com/trader/v1/accounts/abc123/transactions"
        "?startDate=2026-03-28T21%3A10%3A42.000Z&endDate=2026-04-14T21%3A10%3A42.000Z"
        "&types=TRADE%2CDIVIDEND_OR_INTEREST&symbol=AAPL"
    )
    assert payload == [{"activityId": 1}]


def test_get_user_preferences_uses_user_preference_endpoint() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(status_code=200, json=[{"streamerInfo": []}])

    client = SchwabClient(
        access_token="token-123",
        transport=httpx.MockTransport(handler),
    )

    payload = client.get_user_preferences()

    assert captured["url"] == "https://api.schwabapi.com/trader/v1/userPreference"
    assert payload == [{"streamerInfo": []}]
