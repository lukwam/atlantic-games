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
from atlgames import AtlanticGamesGraphQLError
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


# Keys taken from the response can be private too (#3 follow-up): a
# dictionary key in the response appears in the error's field path.
KEY_MARKER_BODY = {"puzzleDate": "2025-01-01", "initialPuzzle": "x", "puzzleSolution": "x",
                   "solutions": {MARKER: []}}


def test_field_paths_hide_keys_from_the_response():
    with pytest.raises(AtlanticGamesParseError) as info:
        parse(BracketCityPuzzle, KEY_MARKER_BODY)
    assert str(info.value) == "The response didn't match BracketCityPuzzle: solutions.*: string_type"


def test_field_paths_keep_field_names_and_indexes():
    from atlgames.models import RabbitholePuzzle
    body = {"id": "53", "publishedAt": "2026-10-09T10:00:00Z",
            "questions": [{"id": "1", "questionText": "q", "canonicalAnswer": "a", "choices": [{}]}]}
    with pytest.raises(AtlanticGamesParseError, match=r"questions\.0\.choices\.0: string_type"):
        parse(RabbitholePuzzle, body)


@pytest.fixture
def key_marker(mock):
    mock.get(BRACKET_CITY).respond(json=KEY_MARKER_BODY)
    return mock


async def test_clients_hide_keys_from_the_response(api, key_marker):
    with pytest.raises(AtlanticGamesParseError, match=r"solutions\.\*: string_type") as info:
        await api("bracket_city", "2025-01-01")
    assert MARKER not in str(info.value)


def test_rest_mcp_and_cli_hide_keys_from_the_response(key_marker, monkeypatch, tmp_path, caplog, capsys):
    response = TestClient(api.app).get("/bracket-city/2025-01-01")
    assert response.status_code == 502 and MARKER not in response.text

    monkeypatch.setattr(mcp_server, "client", lambda: AsyncAtlanticGamesClient(backoff=0))

    async def call():
        async with Client(mcp_server.server) as client:
            return await client.call_tool("bracket_city", {"date": "2025-01-01"})

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(call())
    assert result.is_error and MARKER not in result.content[0].text and MARKER not in caplog.text

    from atlgames.cli import app as cli_main
    monkeypatch.setenv("ATLG_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ATLANTIC_COOKIES", raising=False)
    monkeypatch.setattr(sys, "argv", ["atlg", "bracket-city", "2025-01-01"])
    with pytest.raises(SystemExit):
        cli_main.main()
    captured = capsys.readouterr()
    assert "solutions.*" in captured.err
    assert MARKER not in captured.out + captured.err


def test_live_check_hides_keys_from_the_response(live_check, capsys):
    def check():
        parse(BracketCityPuzzle, KEY_MARKER_BODY)

    result = live_check.run("Check", check)
    assert not result["ok"] and "solutions.*" in result["detail"]
    assert MARKER not in json.dumps(result) and MARKER not in capsys.readouterr().err


# The Atlantic's GraphQL error messages can echo the request or its data
# (#3 follow-up), so errors report only their codes and statuses.
GRAPHQL_MARKER_BODY = {"errors": [{"message": MARKER, "extensions": {"code": "BAD_REQUEST",
                                                                     "http": {"status": 400}}}]}


async def test_graphql_errors_never_include_their_messages(api, mock):
    mock.get(GRAPHQL_URL).respond(json=GRAPHQL_MARKER_BODY)
    with pytest.raises(AtlanticGamesGraphQLError, match=r"\(BAD_REQUEST, HTTP 400\)") as info:
        await api("games")
    assert MARKER not in str(info.value)
    assert info.value.errors == GRAPHQL_MARKER_BODY["errors"]  # still there for callers who need them
    # Codes other than the standard ones could carry anything too.
    mock.get(GRAPHQL_URL).respond(json={"errors": [{"message": MARKER, "extensions": {"code": MARKER}}]})
    with pytest.raises(AtlanticGamesGraphQLError, match=r"\(OTHER\)") as info:
        await api("games")
    assert MARKER not in str(info.value)


def test_graphql_messages_stay_out_of_the_live_check_and_mcp(mock, monkeypatch, capsys, caplog, live_check):
    mock.get(GRAPHQL_URL).respond(json=GRAPHQL_MARKER_BODY)
    from atlgames import AtlanticGamesClient
    with AtlanticGamesClient(backoff=0) as client:
        result = live_check.run("Games hub", client.games)
    assert not result["ok"] and "BAD_REQUEST" in result["detail"]
    assert MARKER not in json.dumps(result) and MARKER not in capsys.readouterr().err

    monkeypatch.setattr(mcp_server, "client", lambda: AsyncAtlanticGamesClient(backoff=0))

    async def call():
        async with Client(mcp_server.server) as client:
            return await client.call_tool("games", {})

    with caplog.at_level(logging.DEBUG):
        tool = asyncio.run(call())
    assert tool.is_error and MARKER not in tool.content[0].text and MARKER not in caplog.text


# Malformed GraphQL envelopes (#3 follow-up) are parse errors, not TypeError
# or KeyError, and keep the REST API's 502.
ENVELOPES = {"a list": [], "no operation": {"data": {}}, "null data": {"data": None},
             "operation not an object": {"data": {"rabbitholePuzzle": [MARKER]}},
             "not GraphQL": {"private": MARKER}}


@pytest.mark.parametrize("body", ENVELOPES.values(), ids=ENVELOPES.keys())
async def test_malformed_graphql_envelopes_are_parse_errors(api, mock, body):
    mock.get(GRAPHQL_URL).respond(json=body)
    with pytest.raises(AtlanticGamesParseError) as info:
        await api("rabbithole", "53")
    assert MARKER not in str(info.value)


@pytest.mark.parametrize("body", ENVELOPES.values(), ids=ENVELOPES.keys())
def test_malformed_graphql_envelopes_are_502s_and_tool_errors(mock, monkeypatch, body):
    mock.get(GRAPHQL_URL).respond(json=body)
    response = TestClient(api.app).get("/rabbithole/53")
    assert response.status_code == 502 and MARKER not in response.text

    monkeypatch.setattr(mcp_server, "client", lambda: AsyncAtlanticGamesClient(backoff=0))

    async def call():
        async with Client(mcp_server.server) as client:
            return await client.call_tool("rabbithole", {"puzzle_id": "53"})

    result = asyncio.run(call())
    assert result.is_error and "expected format" in result.content[0].text
    assert MARKER not in result.content[0].text


# Malformed metadata in a GraphQL error (#9) is a parse error, not
# AttributeError or TypeError, and its values stay out of every message.
METADATA = {
    "http string": {"http": MARKER},
    "response list": {"response": [MARKER]},
    "status object": {"http": {"status": {"private": MARKER}}},
    "code list": {"code": [MARKER]},
    "code object": {"code": {"private": MARKER}},
    "extensions list": [MARKER],
}


@pytest.mark.parametrize("extensions", METADATA.values(), ids=METADATA.keys())
async def test_malformed_graphql_error_metadata_is_a_parse_error(api, mock, extensions):
    mock.get(GRAPHQL_URL).respond(json={"errors": [{"message": MARKER, "extensions": extensions}]})
    with pytest.raises(AtlanticGamesParseError, match="malformed extensions") as info:
        await api("games")
    assert MARKER not in str(info.value)


@pytest.mark.parametrize("extensions", METADATA.values(), ids=METADATA.keys())
def test_malformed_graphql_error_metadata_is_a_502_and_a_tool_error(mock, monkeypatch, caplog, extensions):
    mock.get(GRAPHQL_URL).respond(json={"errors": [{"message": MARKER, "extensions": extensions}]})
    response = TestClient(api.app).get("/rabbithole/53")
    assert response.status_code == 502 and MARKER not in response.text

    monkeypatch.setattr(mcp_server, "client", lambda: AsyncAtlanticGamesClient(backoff=0))

    async def call():
        async with Client(mcp_server.server) as client:
            return await client.call_tool("rabbithole", {"puzzle_id": "53"})

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(call())
    assert result.is_error and "expected format" in result.content[0].text
    assert MARKER not in result.content[0].text and MARKER not in caplog.text


async def test_well_formed_graphql_error_metadata_still_works(api, mock):
    """Absent or null metadata, string statuses and unknown string codes are fine."""
    mock.get(GRAPHQL_URL).respond(json={"errors": [
        {"message": "a"}, {"message": "b", "extensions": None},
        {"message": "c", "extensions": {"http": None, "response": {"status": "400"}, "code": "SOMETHING_NEW"}}]})
    with pytest.raises(AtlanticGamesGraphQLError, match=r"3 error\(s\) \(OTHER, HTTP 400\)"):
        await api("games")
