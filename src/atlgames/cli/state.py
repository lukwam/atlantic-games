"""Shared state for atlg commands: the active profile, cookies and client."""
import datetime
import os
from dataclasses import dataclass
from dataclasses import field

import typer

from atlgames import AtlanticGamesClient
from atlgames.cli.config import Config
from atlgames.cli.dates import parse_date

COOKIES_ENV = "ATLANTIC_COOKIES"


@dataclass
class State:
    """Options from the root command, shared by every subcommand."""

    profile: str | None = None
    cookies: str | None = None
    config: Config = field(default_factory=Config)

    @property
    def active_profile(self) -> str:
        """The profile in use: --profile, then ATLG_PROFILE, then the active one."""
        return self.profile or os.environ.get("ATLG_PROFILE") or self.config.active_profile

    def resolve_cookies(self) -> tuple[str | None, str]:
        """Return the cookies to use and where they came from."""
        if self.cookies:
            return self.cookies, "--cookies"
        if os.environ.get(COOKIES_ENV):
            return os.environ[COOKIES_ENV], COOKIES_ENV
        cookies = self.config.get(self.active_profile, "cookies")
        if cookies:
            return cookies, f"profile {self.active_profile!r}"
        return None, "none"

    def client(self) -> AtlanticGamesClient:
        """Return a client using the resolved cookies."""
        return AtlanticGamesClient(cookies=self.resolve_cookies()[0])


state = State()


def date_arg(value: str, game: str | None = None) -> datetime.date:
    """Parse a date argument, reporting errors as a bad parameter."""
    try:
        return parse_date(value, game)
    except ValueError as err:
        raise typer.BadParameter(str(err)) from None
