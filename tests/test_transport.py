"""Transport tests: retries, error mapping, GraphQL errors and cookies.

Every test runs with both the sync and the async driver.
"""
import datetime
import email.utils
import json

import httpx
import pytest
import respx

from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesGraphQLError
from atlgames import AtlanticGamesHTTPError
from atlgames import AtlanticGamesNotFoundError
from atlgames import AtlanticGamesParseError
from atlgames import AtlanticGamesRateLimitError
from atlgames import transport
from atlgames.transport import GRAPHQL_URL
from atlgames.transport import Request
from atlgames.transport import Settings
from atlgames.transport import graphql

URL = "https://example.test/data.json"


@pytest.fixture(params=["sync", "async"])
def kind(request):
    return request.param


@pytest.fixture
def sleeps(monkeypatch):
    """Record backoff sleeps instead of sleeping."""
    calls = []

    async def asleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(transport.time, "sleep", calls.append)
    monkeypatch.setattr(transport.asyncio, "sleep", asleep)
    return calls


@pytest.fixture
def mock():
    with respx.mock(assert_all_called=False) as router:
        yield router


def settings(**kwargs) -> Settings:
    return Settings(**{"cookies": {}, "user_agent": "test-agent", **kwargs})


async def run(kind: str, operation, config: Settings | None = None):
    config = config or settings()
    if kind == "sync":
        with httpx.Client() as client:
            return transport.run_sync(client, config, operation)
    async with httpx.AsyncClient() as client:
        return await transport.run_async(client, config, operation)


def get(request: Request):
    """An operation that makes one request and returns its result."""
    return (yield request)


async def test_server_errors_and_rate_limits_are_retried_with_backoff(kind, mock, sleeps):
    route = mock.get(URL).mock(side_effect=[
        httpx.Response(503), httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(502),
        httpx.Response(200, json={"ok": True})])
    assert await run(kind, get(Request(URL))) == {"ok": True}
    assert route.call_count == 4
    # 0.5 * 2**attempt, or Retry-After when that's longer
    assert sleeps == [0.5, 3.0, 2.0]


async def test_rate_limit_error_after_retries(kind, mock, sleeps):
    route = mock.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "0"}))
    with pytest.raises(AtlanticGamesRateLimitError) as info:
        await run(kind, get(Request(URL)), settings(retries=2))
    assert route.call_count == 3
    assert info.value.retry_after == 0
    assert info.value.status_code == 429 and info.value.response.status_code == 429
    assert isinstance(info.value, AtlanticGamesHTTPError)


async def test_retries_can_be_turned_off(kind, mock, sleeps):
    route = mock.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(AtlanticGamesHTTPError) as info:
        await run(kind, get(Request(URL)), settings(retries=0))
    assert route.call_count == 1 and sleeps == []
    assert info.value.status_code == 503
    assert type(info.value) is AtlanticGamesHTTPError


async def test_connection_errors_are_retried_then_raised(kind, mock, sleeps):
    route = mock.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(httpx.ConnectError):
        await run(kind, get(Request(URL)), settings(retries=2))
    assert route.call_count == 3
    assert sleeps == [0.5, 1.0]


async def test_connection_error_then_success(kind, mock, sleeps):
    mock.get(URL).mock(side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json=[1])])
    assert await run(kind, get(Request(URL))) == [1]


@pytest.mark.parametrize("status,request_kwargs,error,message", [
    (404, {}, AtlanticGamesNotFoundError, "HTTP 404"),
    (404, {"not_found": "No puzzle"}, AtlanticGamesNotFoundError, "No puzzle"),
    # CloudFront answers 403 for files that don't exist yet.
    (403, {"not_found": "No puzzle"}, AtlanticGamesNotFoundError, "No puzzle"),
    (403, {}, AtlanticGamesAuthenticationError, "HTTP 403"),
    (403, {"not_found": "No puzzle", "auth": True}, AtlanticGamesAuthenticationError, "HTTP 403"),
    (401, {}, AtlanticGamesAuthenticationError, "HTTP 401"),
    (400, {}, AtlanticGamesHTTPError, "HTTP 400"),
])
async def test_client_errors_are_typed_and_not_retried(kind, mock, sleeps, status, request_kwargs, error, message):
    route = mock.get(URL).mock(return_value=httpx.Response(status))
    with pytest.raises(error, match=message) as info:
        await run(kind, get(Request(URL, **request_kwargs)))
    assert route.call_count == 1 and sleeps == []
    assert info.value.status_code == status


def test_retry_after_formats():
    def response(value):
        return httpx.Response(429, headers={"Retry-After": value} if value is not None else {})
    assert transport._retry_after(response("12")) == 12
    assert transport._retry_after(response("1.5")) == 1.5
    assert transport._retry_after(response("-4")) == 0
    assert transport._retry_after(response(None)) is None
    assert transport._retry_after(response("soon")) is None
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=30)
    assert 25 < transport._retry_after(response(email.utils.format_datetime(later, usegmt=True))) <= 30
    past = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
    assert transport._retry_after(response(email.utils.format_datetime(past, usegmt=True))) == 0


def test_delay_is_capped():
    config = settings(backoff=10)
    assert transport._delay(config, 5, None) == 60
    assert transport._delay(config, 0, httpx.Response(429, headers={"Retry-After": "3600"})) == 60


async def test_text_json_and_headers(kind, mock):
    route = mock.get(URL).mock(return_value=httpx.Response(200, text="<html>hi</html>"))
    assert await run(kind, get(Request(URL, {"a": 1, "b": None}, kind="text"))) == "<html>hi</html>"
    sent = route.calls.last.request
    assert dict(sent.url.params) == {"a": "1"}  # unset params aren't sent
    assert sent.headers["User-Agent"] == "test-agent"
    assert "Accept" not in sent.headers or sent.headers["Accept"] != "application/json"
    with pytest.raises(AtlanticGamesParseError, match="Expected JSON"):
        await run(kind, get(Request(URL)))  # e.g. a bot check page
    assert route.calls.last.request.headers["Accept"] == "application/json"


async def test_cookies_only_go_with_auth_requests(kind, mock):
    route = mock.get(URL).mock(return_value=httpx.Response(200, json={}))
    config = settings(cookies={"atljwt6": "secret-token", "other": "x"})
    await run(kind, get(Request(URL)), config)
    assert "Cookie" not in route.calls.last.request.headers
    await run(kind, get(Request(URL, auth=True)), config)
    assert route.calls.last.request.headers["Cookie"] == "atljwt6=secret-token; other=x"
    await run(kind, get(Request(URL, auth=True)))  # no cookies, no header
    assert "Cookie" not in route.calls.last.request.headers


def test_graphql_request():
    request = graphql("""
        query($id: ID!) {
          rabbitholePuzzle(id: $id) { id }
        }""", {"id": "53", "nothing": None}, auth=True, not_found="No puzzle")
    assert request.url == GRAPHQL_URL and request.kind == "graphql" and request.auth
    assert request.params["query"] == "query($id: ID!) { rabbitholePuzzle(id: $id) { id } }"
    assert json.loads(request.params["variables"]) == {"id": "53", "nothing": None}
    assert request.headers["x-api-key"] == transport.GRAPHQL_API_KEY
    assert "variables" not in graphql("{gamesHub{slug}}").params


async def test_graphql_data(kind, mock):
    route = mock.get(GRAPHQL_URL).mock(return_value=httpx.Response(200, json={"data": {"gamesHub": []}}))
    assert await run(kind, get(graphql("{gamesHub{slug}}"))) == {"gamesHub": []}
    assert route.calls.last.request.headers["x-api-key"] == transport.GRAPHQL_API_KEY


# Real error bodies from graphql.theatlantic.com (2026-10).
NOT_FOUND = {"errors": [{"message": "404: Not Found", "path": ["game"], "extensions": {
    "code": "INTERNAL_SERVER_ERROR", "response": {"status": 404, "statusText": "Not Found",
                                                  "body": {"detail": "No Game matches the given query."}}}}],
    "data": None}
BAD_REQUEST = {"errors": [{"message": "Bad request", "path": ["batchGameStates"],
                           "extensions": {"http": {"status": 400}, "code": "BAD_REQUEST"}}], "data": None}
VALIDATION = {"errors": [{"message": "Cannot query field \"nosuchfield\" on type \"Query\".",
                          "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]}


@pytest.mark.parametrize("status,body,request_kwargs,error,message,code", [
    (200, NOT_FOUND, {"not_found": "No game nope"}, AtlanticGamesNotFoundError, "No game nope", 404),
    (200, NOT_FOUND, {}, AtlanticGamesNotFoundError, "404: Not Found", 404),
    (200, {"errors": [{"message": "No Puzzle matches the given query."}]}, {}, AtlanticGamesNotFoundError,
     "No Puzzle matches", 404),
    # The Atlantic answers requests for your data without a login with "Bad request".
    (200, BAD_REQUEST, {"auth": True}, AtlanticGamesAuthenticationError, "atljwt6 cookie", 401),
    (200, BAD_REQUEST, {}, AtlanticGamesGraphQLError, "Bad request", 400),
    (400, VALIDATION, {"auth": True}, AtlanticGamesGraphQLError, "Cannot query field", None),
    (200, {"errors": [{"message": "x", "extensions": {"response": {"status": 403}}}]}, {"auth": True},
     AtlanticGamesAuthenticationError, "missing or expired", 401),
])
async def test_graphql_errors(kind, mock, sleeps, status, body, request_kwargs, error, message, code):
    route = mock.get(GRAPHQL_URL).mock(return_value=httpx.Response(status, json=body))
    request = graphql("{x}", **request_kwargs)
    with pytest.raises(error, match=message) as info:
        await run(kind, get(request))
    assert route.call_count == 1
    assert type(info.value) is error
    assert info.value.status_code == code
    if error is AtlanticGamesGraphQLError:
        assert info.value.errors == body["errors"]


async def test_graphql_server_errors_are_retried(kind, mock, sleeps):
    route = mock.get(GRAPHQL_URL).mock(side_effect=[
        httpx.Response(502, text="<html>Bad gateway</html>"), httpx.Response(200, json={"data": {"x": 1}})])
    assert await run(kind, get(graphql("{x}"))) == {"x": 1}
    assert route.call_count == 2


async def test_graphql_400_without_graphql_body(kind, mock):
    mock.get(GRAPHQL_URL).mock(return_value=httpx.Response(400, text="nope"))
    with pytest.raises(AtlanticGamesHTTPError, match="HTTP 400"):
        await run(kind, get(graphql("{x}")))


async def test_errors_are_thrown_into_operations(kind, mock):
    """An operation can catch a request's error and carry on."""
    mock.get("https://example.test/missing.json").mock(return_value=httpx.Response(404))
    mock.get(URL).mock(return_value=httpx.Response(200, json={"fallback": True}))

    def operation():
        try:
            yield Request("https://example.test/missing.json")
        except AtlanticGamesNotFoundError as error:
            caught = error.status_code
        data = yield Request(URL)
        return caught, data

    assert await run(kind, operation()) == (404, {"fallback": True})


async def test_operation_can_return_from_an_error(kind, mock):
    mock.get(URL).mock(return_value=httpx.Response(404))

    def operation():
        try:
            yield Request(URL)
        except AtlanticGamesNotFoundError:
            return None

    assert await run(kind, operation()) is None


async def test_operation_without_requests(kind):
    def operation():
        return "no requests"
        yield  # pragma: no cover

    assert await run(kind, operation()) == "no requests"


def test_graphql_refuses_mutations():
    with pytest.raises(ValueError, match="read-only"):
        transport.graphql("mutation { saveGameState(items: []) { successCount } }")
    with pytest.raises(ValueError, match="read-only"):
        transport.graphql("  mutation Save($items: [SaveGameStateInput!]!) "
                          "{ saveGameState(items: $items) { successCount } }")
    assert transport.graphql("{ gamesHub { slug } }").url == transport.GRAPHQL_URL
