"""atlg: The Atlantic's games on the command line.

``create_app()`` builds the command line and ``run()`` runs it with atlg's
error handling, so other tools can build their own command line on top of
atlg's.
"""
import re
import sys
from typing import Annotated
from typing import Any
from typing import Optional

import httpx
import typer
from rich.markup import escape

from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesHTTPError
from atlgames import AtlanticGamesNotFoundError
from atlgames import AtlanticGamesParseError
from atlgames import AtlanticGamesRateLimitError
from atlgames import __version__
from atlgames import parse_cookies
from atlgames.cli import archive
from atlgames.cli import output
from atlgames.cli import play
from atlgames.cli import player
from atlgames.cli import puzzles
from atlgames.cli import settings
from atlgames.cli.config import Config
from atlgames.cli.state import COOKIES_ENV
from atlgames.cli.state import state

DEFAULT_NAME = "atlg"
DEFAULT_HELP = """Puzzles, stats and archives from The Atlantic's games: Bracket City, the Crossword,
Caleb's Inferno, Rabbithole, and the archives of Atlantic Trivia and Stacks.

Puzzles work without logging in. For your saved games and stats, run
[bold]{name} auth login[/bold] with your atljwt6 cookie, or set {env}.
"""


def create_app(
    name: str = DEFAULT_NAME,
    help: str | None = None,
    version: str | None = None,
    **typer_kwargs: Any,
) -> typer.Typer:
    """Return a new Typer app with every atlg command.

    Each call returns an independent app. ``name`` and ``help`` set the
    command name and its help, ``version`` is what ``--version`` prints
    (atlantic-games' version by default), and other keyword arguments are
    passed to ``typer.Typer``.
    """
    settings_kwargs = {
        "name": name,
        "no_args_is_help": True,
        "rich_markup_mode": "rich",
        "pretty_exceptions_enable": False,
        "context_settings": {"help_option_names": ["-h", "--help"]},
    }
    settings_kwargs.update(typer_kwargs)
    app = typer.Typer(**settings_kwargs)
    help_text = help or DEFAULT_HELP.format(name=name, env=COOKIES_ENV)
    version_text = f"{name} {version or __version__}"

    def version_callback(value: bool) -> None:
        if value:
            typer.echo(version_text)
            raise typer.Exit()

    @app.callback(help=help_text)
    def root(
        profile: Annotated[
            Optional[str],
            typer.Option("--profile", "-p", envvar="ATLG_PROFILE", help="Profile to use for this command."),
        ] = None,
        cookies: Annotated[
            Optional[str],
            typer.Option("--cookies", help=f"Atlantic cookies for this command, e.g. atljwt6=... (or set "
                                           f"{COOKIES_ENV}).", show_default=False),
        ] = None,
        fmt: output.FormatOption = None,
        version: Annotated[
            bool, typer.Option("--version", callback=version_callback, is_eager=True, help="Show the version.")
        ] = False,
    ) -> None:
        state.config = Config()
        state.profile = profile
        state.cookies = cookies
        output.default_format = fmt or state.config.get(state.active_profile, "format")

    puzzles.register(app)
    player.register(app)
    play.register(app)
    app.command("archive")(archive.archive)
    app.add_typer(settings.build_auth_app(), name="auth")
    app.add_typer(settings.build_config_app(), name="config")
    return app


def cookie_values(raw: str | None) -> set[str]:
    """Return every cookie value that might appear in raw cookies, even malformed ones."""
    if not raw:
        return set()
    values = set(re.findall(r'"value"\s*:\s*"((?:[^"\\]|\\.)*)"', raw))
    for part in re.split(r"[;\n]", raw):
        values.add(part.partition("=")[2].strip())
    try:
        values.update(parse_cookies(raw).values())
    except ValueError:
        pass
    values.add(raw)
    return {value for value in values if len(value) >= 6}


def redact(text: str) -> str:
    """Remove the values of any cookies in use from an error message."""
    for value in sorted(cookie_values(state.resolve_cookies()[0]), key=len, reverse=True):
        text = text.replace(value, "…")
    return text


def run(app: typer.Typer) -> None:
    """Run an app, turning Atlantic errors into short messages and exit codes.

    Exits with 1 for Atlantic errors (rejected cookies, no puzzle, unreadable
    responses, failed requests), 2 for usage errors and 130 for Ctrl-C.
    """
    name = app.info.name or DEFAULT_NAME
    try:
        app()
    except AtlanticGamesAuthenticationError:
        output.err_console.print(
            "[red]The Atlantic rejected the request.[/red] This needs your Atlantic cookies, which are "
            f"missing or have expired. Run [bold]{name} auth login[/bold] or set {COOKIES_ENV}."
        )
        sys.exit(1)
    except AtlanticGamesRateLimitError as err:
        wait = f" Try again in {err.retry_after:g} seconds." if err.retry_after else " Try again later."
        output.err_console.print(f"[red]The server is rate limiting requests.[/red]{wait}")
        sys.exit(1)
    except AtlanticGamesNotFoundError as err:
        output.err_console.print(f"[red]Not found.[/red] {escape(redact(str(err)))}")
        sys.exit(1)
    except AtlanticGamesParseError as err:
        output.err_console.print(f"[red]Couldn't read the response:[/red] {escape(redact(str(err)))}")
        sys.exit(1)
    except (AtlanticGamesHTTPError, httpx.HTTPError) as err:
        output.err_console.print(f"[red]Request failed:[/red] {escape(redact(str(err)))}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as err:  # noqa: BLE001 - never print a traceback that may contain cookies
        output.err_console.print(f"[red]Error:[/red] {type(err).__name__}: {escape(redact(str(err)))}",
                                 highlight=False)
        sys.exit(1)


app = create_app()


def main() -> None:
    """Run atlg."""
    run(app)


if __name__ == "__main__":
    main()
