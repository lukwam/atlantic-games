"""atlg auth and config commands."""
import datetime
from pathlib import Path
from typing import Annotated
from typing import Optional

import typer

from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesClient
from atlgames import parse_cookies
from atlgames.auth import ENTITLEMENTS_COOKIE
from atlgames.auth import SESSION_COOKIE
from atlgames.auth import account_from_cookies
from atlgames.cli import dates
from atlgames.cli.config import KEYS
from atlgames.cli.output import FormatOption
from atlgames.cli.output import console
from atlgames.cli.output import emit
from atlgames.cli.output import key_value_table
from atlgames.cli.state import COOKIES_ENV
from atlgames.cli.state import state


def mask(value: str) -> str:
    """Hide cookie values, keeping the cookie names."""
    try:
        names = list(parse_cookies(value))
    except ValueError:
        return "…"
    return "; ".join(f"{name}=…" for name in names)


def cookie_header(cookies: dict[str, str]) -> str:
    """Return cookies as a Cookie header string."""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def check_login(client: AtlanticGamesClient) -> None:
    """Make one read-only request that needs the login, raising
    AtlanticGamesAuthenticationError if The Atlantic rejects it."""
    client.game_states([("bracket-city", dates.today().isoformat(), "v1")])


def login(
    cookie_file: Annotated[
        Optional[Path],
        typer.Option(
            "--from-file",
            help="Read cookies from a file: a Cookie-Editor JSON export, a Cookie header or the atljwt6 value.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    verify: Annotated[bool, typer.Option(help="Check the cookies with The Atlantic before saving.")] = True,
) -> None:
    """Save your Atlantic cookies to the active profile.

    Copy the atljwt6 cookie from a logged in theatlantic.com browser session
    (your browser's developer tools, under the cookies for .theatlantic.com)
    and paste it when prompted, as either the value or atljwt6=VALUE. Or
    export theatlantic.com's cookies with Cookie-Editor and use --from-file.
    Only atljwt6 (your login) and atljwt (your subscription) are saved.
    """
    if cookie_file:
        cookies = parse_cookies(cookie_file.read_text().strip())
    else:
        text = typer.prompt(f"{SESSION_COOKIE} cookie", hide_input=True).strip()
        cookies = parse_cookies(text if "=" in text else f"{SESSION_COOKIE}={text}")
    if SESSION_COOKIE not in cookies:
        raise typer.BadParameter(f"No {SESSION_COOKIE} cookie found.")
    cookies = {name: cookies[name] for name in (SESSION_COOKIE, ENTITLEMENTS_COOKIE) if name in cookies}
    try:
        account = account_from_cookies(cookies)
    except ValueError as err:
        raise typer.BadParameter(str(err)) from None

    profile = state.active_profile
    if account.expired:
        console.print("[red]These cookies have expired.[/red] Log in to theatlantic.com again and copy "
                      "them again. Nothing was saved.")
        raise typer.Exit(1)
    if verify:
        try:
            check_login(AtlanticGamesClient(cookies=cookies))
        except AtlanticGamesAuthenticationError:
            console.print("[red]The Atlantic rejected these cookies.[/red] Nothing was saved.")
            raise typer.Exit(1) from None
        console.print(f"Logged in as Atlantic user [bold]{account.uuid}[/bold].")
    state.config.set(profile, "cookies", cookie_header(cookies))
    console.print(f"Saved cookies to profile [bold]{profile}[/bold] in {state.config.path}")
    if account.expires_at:
        console.print(f"[dim]The login expires on {account.expires_at:%Y-%m-%d}; theatlantic.com renews it "
                      "as you browse, so copy it again then.[/dim]")


def status(fmt: FormatOption = None) -> None:
    """Show which cookies are in use and whether The Atlantic accepts them."""
    cookies, source = state.resolve_cookies()
    data = {"profile": state.active_profile, "cookies": source, "logged_in": False, "user_id": None}
    if cookies:
        client = state.client()
        account = client.account
        if account is None:
            data["error"] = f"no {SESSION_COOKIE} cookie"
        else:
            data.update(user_id=account.uuid, expires=account.expires_at.isoformat() if account.expires_at else None,
                        premium_access=account.premium_access)
            if account.expired:
                data["error"] = "the cookies have expired"
            else:
                try:
                    check_login(client)
                    data["logged_in"] = True
                except AtlanticGamesAuthenticationError:
                    data["error"] = "The Atlantic rejected the cookies; they may have expired"
            if account.expires_at and data["logged_in"]:
                days = (account.expires_at - datetime.datetime.now(datetime.timezone.utc)).days
                data["expires_in_days"] = days

    def table(data):
        status_text = "[green]logged in[/green]" if data["logged_in"] else "[red]not logged in[/red]"
        yield key_value_table({k: v for k, v in data.items() if k != "logged_in"}, title=status_text)

    emit(data, fmt, table)
    if not data["logged_in"]:
        raise typer.Exit(1)


def logout() -> None:
    """Remove the saved cookies from the active profile."""
    profile = state.active_profile
    if state.config.unset(profile, "cookies"):
        console.print(f"Removed cookies from profile [bold]{profile}[/bold].")
    else:
        console.print(f"Profile [bold]{profile}[/bold] has no saved cookies.")


def check_key(key: str) -> str:
    if key not in KEYS:
        raise typer.BadParameter(f"Unknown setting {key!r}. Settings: {', '.join(KEYS)}.")
    return key


def config_list(fmt: FormatOption = None) -> None:
    """Show the settings in the active profile."""
    profile = state.active_profile
    data = {"profile": profile, **state.config.items(profile)}
    if "cookies" in data:
        data["cookies"] = mask(data["cookies"])
    emit(data, fmt, lambda d: [key_value_table(d)])


def config_get(key: Annotated[str, typer.Argument(help=", ".join(KEYS))]) -> None:
    """Print one setting from the active profile."""
    value = state.config.get(state.active_profile, check_key(key))
    if value is None:
        raise typer.Exit(1)
    typer.echo(value)


def config_set(
    key: Annotated[str, typer.Argument(help=", ".join(KEYS))],
    value: Annotated[Optional[str], typer.Argument(help="Prompted for (hidden) if omitted.")] = None,
) -> None:
    """Save a setting to the active profile."""
    check_key(key)
    if value is None:
        value = typer.prompt(key, hide_input=key == "cookies")
    state.config.set(state.active_profile, key, value)
    console.print(f"Set [cyan]{key}[/cyan] in profile [bold]{state.active_profile}[/bold].")


def config_unset(key: Annotated[str, typer.Argument(help=", ".join(KEYS))]) -> None:
    """Remove a setting from the active profile."""
    if not state.config.unset(state.active_profile, check_key(key)):
        console.print(f"[cyan]{key}[/cyan] isn't set in profile [bold]{state.active_profile}[/bold].")


def config_path() -> None:
    """Print the path of the config file."""
    typer.echo(state.config.path)


def profiles_list(fmt: FormatOption = None) -> None:
    """List profiles and show which one is active."""
    active = state.active_profile
    names = sorted(set(state.config.profiles()) | {active})
    data = [
        {"name": name, "active": name == active, "cookies": bool(state.config.get(name, "cookies"))}
        for name in names
    ]

    def table(data):
        from rich.table import Table

        t = Table(header_style="bold")
        t.add_column("")
        t.add_column("Profile")
        t.add_column("Cookies")
        for row in data:
            t.add_row("*" if row["active"] else "", row["name"], "yes" if row["cookies"] else "")
        yield t

    emit(data, fmt, table)


def profiles_activate(name: str) -> None:
    """Make a profile the default for future commands."""
    state.config.activate(name)
    console.print(f"Activated profile [bold]{name}[/bold].")


def profiles_delete(name: str) -> None:
    """Delete a profile and its settings."""
    if not state.config.delete_profile(name):
        console.print(f"No profile named [bold]{name}[/bold].")
        raise typer.Exit(1)
    console.print(f"Deleted profile [bold]{name}[/bold].")


def build_auth_app() -> typer.Typer:
    """Return a new `auth` command group."""
    app = typer.Typer(help=f"Log in with your Atlantic cookies (or set {COOKIES_ENV}) and check them.",
                      no_args_is_help=True)
    app.command("login")(login)
    app.command("status")(status)
    app.command("logout")(logout)
    return app


def build_config_app() -> typer.Typer:
    """Return a new `config` command group, with its `profiles` subgroup."""
    app = typer.Typer(help="View and change settings.", no_args_is_help=True)
    app.command("list")(config_list)
    app.command("get")(config_get)
    app.command("set")(config_set)
    app.command("unset")(config_unset)
    app.command("path")(config_path)
    profiles = typer.Typer(help="Manage named profiles, such as one per Atlantic account.", no_args_is_help=True)
    profiles.command("list")(profiles_list)
    profiles.command("activate")(profiles_activate)
    profiles.command("delete")(profiles_delete)
    app.add_typer(profiles, name="profiles")
    return app
