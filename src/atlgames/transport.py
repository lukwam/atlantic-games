"""HTTP for the sync and async clients.

Client operations are written once, as generators that yield `Request`s and
receive the decoded responses. `run_sync` drives one with an `httpx.Client`,
`run_async` with an `httpx.AsyncClient`, so both clients share every URL,
parser and error rule.
"""
import asyncio
import datetime
import email.utils
import logging
import re
import time
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Generator
from typing import Mapping

import httpx

from atlgames.exceptions import AtlanticGamesAuthenticationError
from atlgames.exceptions import AtlanticGamesGraphQLError
from atlgames.exceptions import AtlanticGamesHTTPError
from atlgames.exceptions import AtlanticGamesNotFoundError
from atlgames.exceptions import AtlanticGamesParseError
from atlgames.exceptions import AtlanticGamesRateLimitError

logger = logging.getLogger("atlgames")

GRAPHQL_URL = "https://graphql.theatlantic.com/"
#: The Atlantic's public GraphQL key, from its own games pages.
GRAPHQL_API_KEY = "JakhyMEXwa9odtB8gBxFI63ITyKqDGkn7ciGVIJf"
RETRY_STATUSES = (429, 500, 502, 503, 504)
_MUTATION = re.compile(r"\s*mutation\b")


@dataclass
class Request:
    """One GET request.

    `kind` is how to decode the body: "json", "text" or "graphql" (JSON whose
    `errors` are raised and whose `data` is returned). `auth` sends the
    login cookie; it's only ever set for The Atlantic's GraphQL API.
    `not_found` is the message for a 404 (or GraphQL "not found").
    """
    url: str
    params: dict[str, Any] = field(default_factory=dict)
    kind: str = "json"
    auth: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    not_found: str | None = None


Operation = Generator[Request, Any, Any]


def graphql(query: str, variables: Mapping[str, Any] | None = None, auth: bool = False,
            not_found: str | None = None) -> Request:
    """Return a GraphQL GET request (The Atlantic's API accepts GET).

    The library is read-only: mutations are refused before any request.
    """
    if _MUTATION.match(query):
        raise ValueError("atlantic-games is read-only and never sends GraphQL mutations")
    params = {"query": " ".join(query.split())}
    if variables:
        import json
        params["variables"] = json.dumps(variables, separators=(",", ":"))
    return Request(GRAPHQL_URL, params, kind="graphql", auth=auth,
                   headers={"x-api-key": GRAPHQL_API_KEY}, not_found=not_found)


@dataclass
class Settings:
    """What both clients need to send requests."""
    cookies: dict[str, str]
    user_agent: str
    retries: int = 3
    backoff: float = 0.5


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0.0, (when - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _delay(settings: Settings, attempt: int, response: httpx.Response | None) -> float:
    wait = settings.backoff * (2 ** attempt)
    after = _retry_after(response) if response is not None else None
    return min(max(wait, after or 0), 60)


def _should_retry(settings: Settings, attempt: int, response: httpx.Response | None) -> bool:
    if attempt >= settings.retries:
        return False
    return response is None or response.status_code in RETRY_STATUSES


def _build(settings: Settings, request: Request) -> dict:
    headers = {"User-Agent": settings.user_agent, **request.headers}
    if request.kind != "text":
        headers["Accept"] = "application/json"
    if request.auth and settings.cookies:
        # Only The Atlantic's API ever gets the cookies.
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in settings.cookies.items())
    params = {k: v for k, v in request.params.items() if v is not None}
    return {"url": request.url, "params": params, "headers": headers}


def _decode(request: Request, response: httpx.Response):
    """Return the decoded body, or raise the matching error."""
    logger.info("GET %s -> %s", request.url, response.status_code)
    status = response.status_code
    if request.kind == "graphql" and status in (200, 400):
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and ("data" in body or "errors" in body):
            return _graphql_result(request, body, response)
    if status >= 400:
        message = f"HTTP {status} for {request.url}"
        if status == 429:
            raise AtlanticGamesRateLimitError(message, status_code=status, response=response,
                                              retry_after=_retry_after(response))
        if status == 404:
            raise AtlanticGamesNotFoundError(request.not_found or message, status_code=status,
                                             response=response)
        if status in (401, 403):
            # CloudFront answers 403 for files that don't exist (yet).
            if request.not_found and not request.auth:
                raise AtlanticGamesNotFoundError(request.not_found, status_code=status, response=response)
            raise AtlanticGamesAuthenticationError(message, status_code=status, response=response)
        raise AtlanticGamesHTTPError(message, status_code=status, response=response)
    if request.kind == "graphql":
        raise AtlanticGamesParseError("The Atlantic's API response wasn't a GraphQL result")
    if request.kind == "text":
        return response.text
    try:
        return response.json()
    except ValueError:
        raise AtlanticGamesParseError(f"Expected JSON from {request.url}, got something else") from None


# The standard GraphQL error codes (Apollo Server's); other codes are shown
# as OTHER, since they could carry anything.
ERROR_CODES = frozenset({
    "BAD_REQUEST", "BAD_USER_INPUT", "FORBIDDEN", "GRAPHQL_PARSE_FAILED", "GRAPHQL_VALIDATION_FAILED",
    "INTERNAL_SERVER_ERROR", "OPERATION_RESOLUTION_FAILURE", "PERSISTED_QUERY_NOT_FOUND",
    "PERSISTED_QUERY_NOT_SUPPORTED", "UNAUTHENTICATED",
})


_STATUS = re.compile(r"[1-5][0-9]{2}", re.ASCII)


def _error_metadata(error: dict) -> tuple[int | None, str | None]:
    """Return a GraphQL error's HTTP status and safe code, either of which
    may be missing.

    Raises AtlanticGamesParseError, naming the field but not its value, if
    the metadata isn't the shape GraphQL servers send.
    """
    def malformed(field: str) -> AtlanticGamesParseError:
        return AtlanticGamesParseError(f"The Atlantic's API error had a malformed {field}")

    ext = error.get("extensions")
    if ext is None:
        return None, None
    if not isinstance(ext, dict):
        raise malformed("extensions")
    status = None
    for key in ("http", "response"):
        info = ext.get(key)
        if info is None:
            continue
        if not isinstance(info, dict):
            raise malformed(f"extensions.{key}")
        value = info.get("status")
        if value is None:
            continue
        # An HTTP status, as a number or three ASCII digits. isdigit() isn't
        # enough: it accepts digits int() rejects, such as "²".
        if isinstance(value, str) and _STATUS.fullmatch(value):
            value = int(value)
        if not isinstance(value, int) or isinstance(value, bool) or not 100 <= value <= 599:
            raise malformed(f"extensions.{key}.status")
        status = status or value
    code = ext.get("code")
    if code is not None and not isinstance(code, str):
        raise malformed("extensions.code")
    return status, None if code is None else code if code in ERROR_CODES else "OTHER"


def _graphql_result(request: Request, body: dict, response: httpx.Response):
    errors = body.get("errors") or []
    if not errors:
        data = body.get("data")
        if not isinstance(data, dict):
            raise AtlanticGamesParseError("The Atlantic's API response had no data")
        return data
    if not isinstance(errors, list) or not all(isinstance(e, dict) for e in errors):
        raise AtlanticGamesParseError("The Atlantic's API response had malformed errors")
    statuses, codes = set(), set()
    for error in errors:
        status, code = _error_metadata(error)
        if status:
            statuses.add(status)
        if code:
            codes.add(code)
    # Messages are The Atlantic's own text, which can echo the request or its
    # data, so they stay in `errors` and out of the error message.
    summary = ", ".join([*sorted(codes), *(f"HTTP {s}" for s in sorted(statuses))]) or "no details"
    if 404 in statuses or any("No " in str(e.get("message")) and "matches" in str(e.get("message"))
                              for e in errors):
        raise AtlanticGamesNotFoundError(request.not_found or f"The Atlantic's API found nothing ({summary})",
                                         status_code=404, response=response)
    if request.auth and (400 in statuses or 401 in statuses or 403 in statuses):
        raise AtlanticGamesAuthenticationError(
            "The Atlantic rejected the request for your data; the atljwt6 cookie is "
            f"missing or expired ({summary})", status_code=401, response=response)
    raise AtlanticGamesGraphQLError(f"The Atlantic's API returned {len(errors)} error(s) ({summary})",
                                    errors=errors, status_code=max(statuses, default=None), response=response)


def run_sync(client: httpx.Client, settings: Settings, operation: Operation):
    """Run an operation with a sync httpx client and return its result.

    Errors from a request are thrown into the operation, so it can catch
    them (e.g. to fall back after a 404).
    """
    try:
        request = next(operation)
        while True:
            try:
                response = _send_sync(client, settings, request)
            except AtlanticGamesHTTPError as error:
                request = operation.throw(error)
            else:
                request = operation.send(response)
    except StopIteration as stop:
        return stop.value


def _send_sync(client: httpx.Client, settings: Settings, request: Request):
    attempt = 0
    while True:
        response = None
        try:
            response = client.get(**_build(settings, request))
        except httpx.TransportError:
            if not _should_retry(settings, attempt, None):
                raise
        else:
            if not _should_retry(settings, attempt, response):
                return _decode(request, response)
        time.sleep(_delay(settings, attempt, response))
        attempt += 1


async def run_async(client: httpx.AsyncClient, settings: Settings, operation: Operation):
    """Run an operation with an async httpx client and return its result."""
    try:
        request = next(operation)
        while True:
            try:
                response = await _send_async(client, settings, request)
            except AtlanticGamesHTTPError as error:
                request = operation.throw(error)
            else:
                request = operation.send(response)
    except StopIteration as stop:
        return stop.value


async def _send_async(client: httpx.AsyncClient, settings: Settings, request: Request):
    attempt = 0
    while True:
        response = None
        try:
            response = await client.get(**_build(settings, request))
        except httpx.TransportError:
            if not _should_retry(settings, attempt, None):
                raise
        else:
            if not _should_retry(settings, attempt, response):
                return _decode(request, response)
        await asyncio.sleep(_delay(settings, attempt, response))
        attempt += 1
