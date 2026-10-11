"""Atlantic Games exceptions."""
import httpx


class AtlanticGamesError(Exception):
    """Base class for Atlantic Games errors."""


class AtlanticGamesHTTPError(AtlanticGamesError):
    """A server returned an error.

    `status_code` is the HTTP status (GraphQL errors carry the status of the
    service behind them, e.g. 404 for an unknown game), and `response` is the
    `httpx.Response`, when there is one.
    """

    def __init__(self, message: str, status_code: int | None = None,
                 response: httpx.Response | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class AtlanticGamesAuthenticationError(AtlanticGamesHTTPError):
    """The request needs you to be logged in.

    Usually the `atljwt6` cookie is missing or has expired (it lasts 30 days).
    The Atlantic answers unauthenticated requests for your data with
    "Bad request", so that's mapped to this error for those requests.
    """


class AtlanticGamesRateLimitError(AtlanticGamesHTTPError):
    """A server is rate limiting requests (HTTP 429), even after retrying.

    `retry_after` is how many seconds it asked to wait, if it said.
    """

    def __init__(self, *args, retry_after: float | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class AtlanticGamesNotFoundError(AtlanticGamesHTTPError):
    """There's no data for the request, e.g. a date with no puzzle or a
    puzzle that hasn't been published yet."""


class AtlanticGamesGraphQLError(AtlanticGamesHTTPError):
    """The Atlantic's GraphQL API returned errors.

    `errors` is the list of GraphQL error objects.
    """

    def __init__(self, message: str, errors: list | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.errors = errors or []


class AtlanticGamesParseError(AtlanticGamesError, ValueError):
    """A page or file didn't contain the expected game data.

    For crosswords this can mean Amuse Labs changed how puzzles are encoded.
    """


class AtlanticGamesExportError(AtlanticGamesError, ValueError):
    """A puzzle can't be converted to a file format.

    `reasons` lists what the format can't represent.
    """

    def __init__(self, fmt: str, reasons: list[str]):
        self.format = fmt
        self.reasons = reasons
        super().__init__(f"Can't export to {fmt}: " + "; ".join(reasons))
