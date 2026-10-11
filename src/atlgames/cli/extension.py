"""Public API for building command lines on top of atlg.

Requires the `cli` extra. Everything here is a stable, documented interface;
the other modules in ``atlgames.cli`` are internal and may change.

Example, a ``mytool`` command with every atlg command plus a ``sync`` group::

    import typer
    from atlgames.cli.extension import FormatOption, create_app, emit, get_client, run

    app = create_app(name="mytool", help="My Atlantic tools.")
    sync = typer.Typer(help="Sync my games.")
    app.add_typer(sync, name="sync")

    @sync.command("bracket-city")
    def sync_bracket_city(fmt: FormatOption = None) -> None:
        games = get_client().bracket_city_games("2026-10-01")
        emit([{"date": g.gameDate, "progress": g.progress.value} for g in games], fmt)

    def main() -> None:
        run(app)

Commands get atlg's root options (--profile, --cookies, --format and
--version) and error handling for free.
"""
import datetime
from typing import Any

from atlgames import AtlanticGamesClient
from atlgames.cli.app import create_app
from atlgames.cli.app import run
from atlgames.cli.output import FormatOption
from atlgames.cli.output import TableRenderer
from atlgames.cli.output import console
from atlgames.cli.output import emit as _emit
from atlgames.cli.output import err_console
from atlgames.cli.output import key_value_table
from atlgames.cli.state import date_arg
from atlgames.cli.state import state

__all__ = [
    "FormatOption",
    "TableRenderer",
    "active_profile",
    "console",
    "create_app",
    "emit",
    "err_console",
    "get_client",
    "get_setting",
    "key_value_table",
    "parse_date",
    "resolve_cookies",
    "run",
]


def emit(data: Any, fmt: str | None = None, table: TableRenderer | None = None) -> None:
    """Print JSON-compatible data in the requested --format.

    ``fmt`` is the command's FormatOption value; None uses the root --format,
    then the profile's format setting, then a table. ``table`` is a function
    that takes ``data`` and yields Rich renderables for the table format;
    without one, dicts become key/value tables and lists become tables with
    one row per item.
    """
    _emit(data, fmt, table)


def get_client() -> AtlanticGamesClient:
    """Return an AtlanticGamesClient with the cookies atlg would use.

    Cookies come from --cookies, then ATLANTIC_COOKIES, then the active profile.
    """
    return state.client()


def resolve_cookies() -> tuple[str | None, str]:
    """Return the cookies atlg would use and where they came from."""
    return state.resolve_cookies()


def active_profile() -> str:
    """Return the profile in use: --profile, then ATLG_PROFILE, then the active one."""
    return state.active_profile


def get_setting(key: str) -> str | None:
    """Return a setting from the active profile's config.

    Extensions may store their own settings in the profile, using a prefix
    such as ``mytool.project``.
    """
    return state.config.get(state.active_profile, key)


def parse_date(value: str, game: str | None = None) -> datetime.date:
    """Parse a date argument like atlg does: YYYY-MM-DD, today, yesterday,
    tomorrow, a weekday, or "first"/"last" for a game. Raises a usage error
    if invalid.
    """
    return date_arg(value, game)
