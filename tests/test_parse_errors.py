"""Malformed responses: AtlanticGamesParseError, never the response's values (#3).

Responses that are valid JSON but the wrong shape become
AtlanticGamesParseError, naming the model and fields but never the values,
which can be your saved games. Every surface is checked with a made-up
private marker: the clients, the REST API, the MCP server, the CLI and the
live check.
"""
import asyncio
import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from atlgames import AsyncAtlanticGamesClient
from atlgames import AtlanticGamesParseError
from atlgames import api
from atlgames import mcp_server
from atlgames.models import BracketCityPuzzle
from atlgames.models import parse
from atlgames.transport import GRAPHQL_URL

MARKER = "SYNTHETIC_PRIVATE_INPUT"
BRACKET_CITY = "https://d2gknrezp32xyk.cloudfront.net/puzzles/2025-01-01.json"

MALFORMED = {
    "missing field": {"private": MARKER},
    "wrong nested type": {"puzzleDate": "2025-01-01", "initialPuzzle": "x", "puzzleSolution": "x",
                          "solutions": {"private": {"private": MARKER}}},
    "not an object": [MARKER],
    "not JSON object at all": MARKER,
}


@pytest.mark.parametrize("body", MALFORMED.values(), ids=MALFORMED.keys())
async def test_clients_raise_parse_errors_without_values(api, mock, body):
    mock.get(BRACKET_CITY).respond(json=body)
    with pytest.raises(AtlanticGamesParseError, match="BracketCityPuzzle") as info:
        await api("bracket_city", "2025-01-01")
    assert MARKER not in str(info.value)
    # No chained ValidationError, whose traceback could show the values.
    assert info.value.__cause__ is None
    assert info.value.__context__ is None or info.value.__suppress_context__


async def test_nested_lists_and_list_responses(api, mock):
    mock.get(GRAPHQL_URL).respond(json={"data": {"rabbitholePuzzle": {
        "id": "53", "publishedAt": "2026-10-09T10:00:00Z", "questions": MARKER}}})
    with pytest.raises(AtlanticGamesParseError, match=r"RabbitholePuzzle: questions: list_type") as info:
        await api("rabbithole", "53")
    assert MARKER not in str(info.value)
    mock.get(GRAPHQL_URL).respond(json={"data": {"gamesHub": {"private": MARKER}}})
    with pytest.raises(AtlanticGamesParseError, match="list of Game") as info:
        await api("games")
    assert MARKER not in str(info.value)


def test_messages_name_the_fields_and_error_types():
    with pytest.raises(AtlanticGamesParseError) as info:
        parse(BracketCityPuzzle, {"puzzleDate": 20250101, "initialPuzzle": "x", "puzzleSolution": "x"})
    assert str(info.value) == ("The response didn't match BracketCityPuzzle: puzzleDate: string_type; "
                               "solutions: missing")


def test_model_validation_errors_hide_values_too():
    """Even a ValidationError raised directly by a model hides the input."""
    with pytest.raises(ValueError) as info:
        BracketCityPuzzle(puzzleDate="2025-01-01", initialPuzzle="x", puzzleSolution="x", solutions=MARKER)
    assert MARKER not in str(info.value)


def test_rest_api_returns_502_without_values(mock):
    mock.get(BRACKET_CITY).respond(json={"private": MARKER})
    response = TestClient(api.app).get("/bracket-city/2025-01-01")
    assert response.status_code == 502
    assert MARKER not in response.text


def test_mcp_tool_error_and_log_have_no_values(mock, monkeypatch, caplog):
    mock.get(BRACKET_CITY).respond(json={"private": MARKER})
    monkeypatch.setattr(mcp_server, "client", lambda: AsyncAtlanticGamesClient(backoff=0))

    async def call():
        async with Client(mcp_server.server) as client:
            return await client.call_tool("bracket_city", {"date": "2025-01-01"})

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(call())
    assert result.is_error and "expected format" in result.content[0].text
    assert MARKER not in result.content[0].text
    assert MARKER not in caplog.text


def test_cli_error_has_no_values(mock, tmp_path, monkeypatch, capsys):
    from typer.testing import CliRunner

    from atlgames.cli import app as cli_main
    monkeypatch.setenv("ATLG_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ATLANTIC_COOKIES", raising=False)
    mock.get(BRACKET_CITY).respond(json={"private": MARKER})
    monkeypatch.setattr(sys, "argv", ["atlg", "bracket-city", "2025-01-01"])
    result = CliRunner().invoke(cli_main.app, ["bracket-city", "2025-01-01"])
    assert result.exit_code != 0
    assert MARKER not in result.output
    with pytest.raises(SystemExit):
        cli_main.main()
    err = capsys.readouterr().err
    assert "Couldn't read the response" in err and "BracketCityPuzzle" in err
    assert MARKER not in err


@pytest.fixture
def live_check():
    path = Path(__file__).parent.parent / "scripts" / "live_check.py"
    spec = importlib.util.spec_from_file_location("live_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("error", [KeyError(MARKER), TypeError(MARKER), ValueError(MARKER)])
def test_live_check_failures_have_no_values(live_check, capsys, error):
    def check():
        raise error

    result = live_check.run("Check", check)
    assert not result["ok"] and result["detail"].startswith(type(error).__name__ + " in check")
    assert MARKER not in json.dumps(result)
    assert MARKER not in capsys.readouterr().err


def test_live_check_keeps_safe_messages(live_check):
    def check():
        raise AtlanticGamesParseError("The response didn't match BracketCityPuzzle: solutions: missing")

    assert live_check.run("Check", check)["detail"].endswith("solutions: missing")

    def failed_assertion():
        assert False, "31 dailies"

    assert "31 dailies" in live_check.run("Check", failed_assertion)["detail"]
