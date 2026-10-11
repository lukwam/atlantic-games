"""Tests for the public CLI extension API in atlgames.cli.extension."""
import datetime
import json
from unittest import mock

import pytest
import typer
from typer.testing import CliRunner

from atlgames.cli import dates
from atlgames.cli import extension
from atlgames.cli import output
from atlgames.cli.extension import FormatOption
from atlgames.cli.extension import create_app
from atlgames.cli.extension import emit
from atlgames.cli.extension import key_value_table
from atlgames.cli.state import State
from atlgames.models import BracketCityGame

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("ATLANTIC_COOKIES", raising=False)
    monkeypatch.delenv("ATLG_PROFILE", raising=False)
    monkeypatch.setattr(dates, "today", lambda: datetime.date(2026, 10, 11))
    output.default_format = None


def tool_app() -> typer.Typer:
    """An extension app with a sync group, like gamesapp's."""
    app = create_app(name="gtool", help="Games app tools.", version="9.9.9")
    sync = typer.Typer(help="Sync games.")
    app.add_typer(sync, name="sync")

    @sync.command("whoami")
    def whoami(fmt: FormatOption = None) -> None:
        cookies, source = extension.resolve_cookies()
        emit({"profile": extension.active_profile(), "cookies": cookies, "source": source}, fmt)

    @sync.command("bracket-city")
    def bracket_city(date: str = "today", fmt: FormatOption = None) -> None:
        day = extension.parse_date(date, "bracket-city")
        game = extension.get_client().bracket_city_game(day.isoformat())
        emit({"date": game.gameDate, "progress": game.progress.value}, fmt,
             table=lambda data: [key_value_table(data, title="Bracket City")])

    return app


def test_extension_app_has_every_atlg_command():
    def names(app):
        return {c.name for c in app.registered_commands} | {g.name for g in app.registered_groups}

    assert names(create_app()) <= names(tool_app())
    assert {"bracket-city", "crossword", "stats", "auth", "config", "history", "sync"} <= names(tool_app())


def test_name_help_and_version():
    app = tool_app()
    assert runner.invoke(app, ["--version"]).stdout == "gtool 9.9.9\n"
    assert "Games app tools." in runner.invoke(app, ["--help"]).stdout


def test_extension_commands_get_root_options():
    result = runner.invoke(tool_app(), ["--profile", "alice", "--cookies", "atljwt6=x", "-f", "json",
                                        "sync", "whoami"])
    assert json.loads(result.stdout) == {"profile": "alice", "cookies": "atljwt6=x", "source": "--cookies"}


def test_extension_commands_use_the_client_formats_and_tables(monkeypatch):
    client = mock.Mock()
    client.bracket_city_game.return_value = BracketCityGame(
        gameKey="2026-10-10:bracket-city:v1", gameSlug="bracket-city", gameDate="2026-10-10",
        gameId="v1", progress="complete")
    monkeypatch.setattr(State, "client", lambda self: client)

    assert runner.invoke(tool_app(), ["sync", "bracket-city", "--date", "yesterday", "-f", "value(progress)"]
                         ).stdout == "complete\n"
    client.bracket_city_game.assert_called_with("2026-10-10")
    table = runner.invoke(tool_app(), ["sync", "bracket-city"])
    assert table.exit_code == 0 and "Bracket City" in table.stdout
    assert runner.invoke(tool_app(), ["sync", "bracket-city", "--date", "someday"]).exit_code == 2


def test_extension_get_setting(monkeypatch):
    monkeypatch.setattr(State, "active_profile", property(lambda self: "default"))
    with mock.patch.object(extension.state.config, "get", return_value="proj") as get:
        assert extension.get_setting("gtool.project") == "proj"
    get.assert_called_with("default", "gtool.project")
