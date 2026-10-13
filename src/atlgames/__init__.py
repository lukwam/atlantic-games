"""Unofficial client for The Atlantic's games."""
__version__ = "0.4.2"

from atlgames.auth import Account  # noqa: E402
from atlgames.auth import parse_cookies  # noqa: E402
from atlgames.client import AsyncAtlanticGamesClient  # noqa: E402
from atlgames.client import AtlanticGamesClient  # noqa: E402
from atlgames.exceptions import AtlanticGamesAuthenticationError  # noqa: E402
from atlgames.exceptions import AtlanticGamesError  # noqa: E402
from atlgames.exceptions import AtlanticGamesExportError  # noqa: E402
from atlgames.exceptions import AtlanticGamesGraphQLError  # noqa: E402
from atlgames.exceptions import AtlanticGamesHTTPError  # noqa: E402
from atlgames.exceptions import AtlanticGamesNotFoundError  # noqa: E402
from atlgames.exceptions import AtlanticGamesParseError  # noqa: E402
from atlgames.exceptions import AtlanticGamesRateLimitError  # noqa: E402
from atlgames.models import CrosswordSeries  # noqa: E402

__all__ = [
    "Account",
    "AsyncAtlanticGamesClient",
    "AtlanticGamesAuthenticationError",
    "AtlanticGamesClient",
    "AtlanticGamesError",
    "AtlanticGamesExportError",
    "AtlanticGamesGraphQLError",
    "AtlanticGamesHTTPError",
    "AtlanticGamesNotFoundError",
    "AtlanticGamesParseError",
    "AtlanticGamesRateLimitError",
    "CrosswordSeries",
    "parse_cookies",
]
