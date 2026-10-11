"""Atlantic Games API tests.

Most tests replace the client with a mock; the rest mock the upstream HTTP
requests with respx. None of them use the network or real cookies.
"""
import base64
import json
from unittest import mock

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlgames import AsyncAtlanticGamesClient
from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesGraphQLError
from atlgames import AtlanticGamesHTTPError
from atlgames import AtlanticGamesNotFoundError
from atlgames import AtlanticGamesParseError
from atlgames import AtlanticGamesRateLimitError
from atlgames import api as main
from atlgames.models import BracketCityGame
from atlgames.models import BracketCityPuzzle
from atlgames.models import CrosswordListing
from atlgames.models import CrosswordPlay
from atlgames.models import CrosswordPuzzle
from atlgames.models import Game
from atlgames.models import RabbitholeGame
from atlgames.models import RabbitholePuzzle
from atlgames.models import StacksPuzzle
from atlgames.models import TriviaArticle
from atlgames.transport import GRAPHQL_URL

BRACKET_CITY_URL = "https://d2gknrezp32xyk.cloudfront.net/puzzles"


def jwt(claims: dict) -> str:
    """Return an unsigned JWT with the claims."""
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


TOKEN = jwt({"uuid": "user-1", "iat": 1790000000, "exp": 4102444800})

BRACKET_CITY = {
    "puzzleDate": "2026-10-11",
    "initialPuzzle": "[[pine] tree] house",
    "puzzleSolution": "treehouse",
    "solutions": {"pine": "cone", "cone tree": "tree"},
}

CROSSWORD = {
    "id": "atlantic_20261009",
    "title": "Friday",
    "author": "A. Constructor; edited by An Editor",
    "w": 2,
    "h": 1,
    "box": [["A"], ["B"]],
    "placedWords": [{"originalTerm": "AB", "nBoxes": 2, "x": 0, "y": 0, "acrossNotDown": True,
                     "clueNum": "1", "clue": {"clue": "Start"}}],
    "publishTime": 1791000000000,
    "series": "atlantic",
}

RABBITHOLE = {
    "id": "42",
    "publishedAt": "2026-10-09T10:00:00Z",
    "questions": [{"id": "1", "questionText": "<p>Q?</p>", "canonicalAnswer": "A"}],
}

STATE = {"gameKey": "k", "gameDate": "2026-10-09", "progress": "complete",
         "updatedAt": 1791000000000, "userUUID": "user-1"}


@pytest.fixture
def atl():
    """Serve the API with a mock client and yield the mock."""
    fake = mock.Mock(spec=AsyncAtlanticGamesClient)
    for name in ("bracket_city", "bracket_city_dates", "bracket_city_game", "bracket_city_games",
                 "crosswords", "crossword", "crossword_play", "rabbithole", "rabbithole_puzzles",
                 "rabbithole_game", "rabbithole_games", "trivia_articles", "trivia", "stacks",
                 "stacks_puzzles", "games", "game"):
        setattr(fake, name, mock.AsyncMock(name=name))
    fake.account = None
    main.app.dependency_overrides[main.get_client] = lambda: fake
    yield fake
    main.app.dependency_overrides.clear()


client = TestClient(main.app)


# Bracket City

def test_bracket_city_latest_and_date(atl):
    """Bracket City puzzles come back with their solutions."""
    atl.bracket_city.return_value = BracketCityPuzzle(**BRACKET_CITY)
    response = client.get("/bracket-city/latest")
    assert response.status_code == 200
    assert response.json()["solutions"]["pine"] == "cone"
    atl.bracket_city.assert_awaited_with()
    assert client.get("/bracket-city/2026-10-11").status_code == 200
    atl.bracket_city.assert_awaited_with("2026-10-11")


def test_bracket_city_dates(atl):
    atl.bracket_city_dates.return_value = ["2025-01-01", "2025-01-02"]
    assert client.get("/bracket-city/dates").json() == ["2025-01-01", "2025-01-02"]


def test_bad_dates_are_rejected_before_calling_the_atlantic(atl):
    """Dates are validated by the API, so bad ones are 422s, not 500s."""
    assert client.get("/bracket-city/2026-13-01").status_code == 422
    assert client.get("/bracket-city/games?date_start=yesterday").status_code == 422
    assert client.get("/crosswords/daily/not-a-date").status_code == 422
    atl.bracket_city.assert_not_awaited()
    atl.bracket_city_games.assert_not_awaited()
    atl.crossword.assert_not_awaited()


def test_bracket_city_games_and_stats(atl):
    """Saved games and stats pass the date range through."""
    games = [
        BracketCityGame(**{**STATE, "gameDate": "2026-10-09"}, gameSlug="bracket-city", gameId="v1",
                        gameState={"isComplete": True, "totalKeystrokes": 10, "minimumKeystrokes": 10}),
        BracketCityGame(**{**STATE, "gameDate": "2026-10-10"}, gameSlug="bracket-city", gameId="v1",
                        gameState={"isComplete": True, "totalKeystrokes": 20, "minimumKeystrokes": 10,
                                   "wrongGuesses": 2}),
    ]
    atl.bracket_city_games.return_value = games
    response = client.get("/bracket-city/games?date_start=2026-10-01&date_end=2026-10-31")
    assert response.status_code == 200
    assert [g["gameDate"] for g in response.json()] == ["2026-10-09", "2026-10-10"]
    atl.bracket_city_games.assert_awaited_with("2026-10-01", "2026-10-31")

    stats = client.get("/bracket-city/stats").json()
    assert stats["completed"] == 2
    assert stats["perfect"] == 1
    assert stats["wrong_guesses"] == 2
    assert stats["completed_dates"] == ["2026-10-09", "2026-10-10"]
    atl.bracket_city_games.assert_awaited_with(None, None)


def test_bracket_city_game_none_is_null(atl):
    """A date with no saved game returns null."""
    atl.bracket_city_game.return_value = None
    response = client.get("/bracket-city/2026-10-11/game")
    assert response.status_code == 200
    assert response.json() is None
    atl.bracket_city_game.assert_awaited_with("2026-10-11")


# Crosswords

def test_crossword_list(atl):
    """Series names are daily and inferno in the API."""
    atl.crosswords.return_value = [CrosswordListing(puzzleId="atlantic_20261009", series="atlantic")]
    response = client.get("/crosswords/puzzles?series=inferno&date_start=2026-10-01&limit=5")
    assert response.status_code == 200
    assert response.json()[0]["puzzleId"] == "atlantic_20261009"
    atl.crosswords.assert_awaited_with("inferno", "2026-10-01", None, 5)
    assert client.get("/crosswords/puzzles?series=atlantic").status_code == 422
    assert client.get("/crosswords/puzzles?limit=0").status_code == 422


def test_crossword_routes(atl):
    atl.crossword.return_value = CrosswordPuzzle(**CROSSWORD)
    assert client.get("/crosswords/daily/latest").json()["id"] == "atlantic_20261009"
    atl.crossword.assert_awaited_with(series="daily")
    assert client.get("/crosswords/inferno/2026-10-09").status_code == 200
    atl.crossword.assert_awaited_with(date="2026-10-09", series="inferno")
    assert client.get("/crosswords/id/atlantic_20261009?series=inferno").status_code == 200
    atl.crossword.assert_awaited_with(puzzle_id="atlantic_20261009", series="inferno")
    assert client.get("/crosswords/weekly/latest").status_code == 422


def test_crossword_play(atl):
    atl.crossword_play.return_value = CrosswordPlay(id="atlantic_20261009", playState=2, timeTaken=300)
    response = client.get("/crosswords/id/atlantic_20261009/play")
    assert response.status_code == 200
    assert response.json()["timeTaken"] == 300
    atl.crossword_play.assert_awaited_with("atlantic_20261009", "daily")


# Rabbithole

def test_rabbithole_routes(atl):
    puzzle = RabbitholePuzzle(**RABBITHOLE)
    atl.rabbithole.return_value = puzzle
    atl.rabbithole_puzzles.return_value = [puzzle]
    assert client.get("/rabbithole/latest").json()["questions"][0]["canonicalAnswer"] == "A"
    atl.rabbithole.assert_awaited_with()
    assert client.get("/rabbithole/42").status_code == 200
    atl.rabbithole.assert_awaited_with("42")
    assert len(client.get("/rabbithole/puzzles?date_end=2026-10-31").json()) == 1
    atl.rabbithole_puzzles.assert_awaited_with(None, "2026-10-31")


def test_rabbithole_games_and_stats(atl):
    game = RabbitholeGame(**STATE, gameSlug="rabbithole", gameId="42",
                          gameState={"score": 21, "questionResults": ["correct_first_try"] * 7})
    atl.rabbithole_games.return_value = [game]
    atl.rabbithole_game.return_value = game
    assert client.get("/rabbithole/games").json()[0]["gameState"]["score"] == 21
    stats = client.get("/rabbithole/stats?date_start=2026-08-12").json()
    assert stats["completed"] == 1
    assert stats["perfect"] == 1
    assert stats["average_score"] == 21
    atl.rabbithole_games.assert_awaited_with("2026-08-12", None)
    assert client.get("/rabbithole/42/game").json()["gameId"] == "42"
    atl.rabbithole_game.assert_awaited_with("42")


# Trivia, Stacks and the games hub

def test_trivia(atl):
    atl.trivia_articles.return_value = [TriviaArticle(id="BlogArticle:688280", title="Trivia")]
    atl.trivia.return_value = TriviaArticle(id="BlogArticle:688280", questions=[
        {"id": "1", "questionText": "Q?", "canonicalAnswer": "A"}])
    assert client.get("/trivia?limit=3").json()[0]["id"] == "BlogArticle:688280"
    atl.trivia_articles.assert_awaited_with(3)
    assert client.get("/trivia/688280").json()["questions"][0]["canonicalAnswer"] == "A"
    atl.trivia.assert_awaited_with("688280")
    assert client.get("/trivia/nope").status_code == 422


def test_stacks(atl):
    puzzle = StacksPuzzle(date="2026-08-24", id=433, wordStrings=["AB"], blackPos="", solution=[0])
    atl.stacks_puzzles.return_value = [puzzle]
    atl.stacks.return_value = puzzle
    assert client.get("/stacks").json()[0]["id"] == 433
    assert client.get("/stacks/2026-08-24").json()["date"] == "2026-08-24"
    atl.stacks.assert_awaited_with("2026-08-24")


def test_games_hub(atl):
    atl.games.return_value = [Game(name="Bracket City", slug="bracket-city")]
    atl.game.return_value = Game(name="Stacks", slug="stacks")
    assert client.get("/games").json()[0]["slug"] == "bracket-city"
    assert client.get("/games/stacks").json()["name"] == "Stacks"
    atl.game.assert_awaited_with("stacks")


# Errors

@pytest.mark.parametrize("error,status", [
    (AtlanticGamesNotFoundError("No Bracket City puzzle for 2024-01-01", status_code=404), 404),
    (AtlanticGamesAuthenticationError("This needs you to be logged in"), 401),
    (AtlanticGamesRateLimitError("HTTP 429", status_code=429), 429),
    (AtlanticGamesParseError("No game data"), 502),
    (AtlanticGamesGraphQLError("Something broke", errors=[{"message": "Something broke"}]), 502),
    (AtlanticGamesHTTPError("HTTP 500 for https://example.com", status_code=500), 502),
    (httpx.ConnectError("boom"), 502),
])
def test_errors_map_to_http_statuses(atl, error, status):
    """Client errors become HTTP errors with a reason, not 500s."""
    atl.bracket_city.side_effect = error
    response = client.get("/bracket-city/2024-01-01")
    assert response.status_code == status
    assert response.json()["detail"]


def test_rate_limit_sends_retry_after(atl):
    atl.games.side_effect = AtlanticGamesRateLimitError("HTTP 429", status_code=429, retry_after=2.5)
    response = client.get("/games")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3"


def test_account_needs_a_login(atl):
    assert client.get("/account").status_code == 401


# Cookies and app setup (real client, mocked HTTP)

@respx.mock
def test_only_atlantic_cookies_reach_the_atlantic():
    """Login cookies are passed to The Atlantic's API; other cookies never are."""
    route = respx.get(GRAPHQL_URL).mock(return_value=httpx.Response(200, json={"data": {
        "batchGameStates": {"items": [], "unprocessedKeys": []}}}))
    app_client = TestClient(main.app, cookies={"atljwt6": TOKEN, "session": "other-site"})
    response = app_client.get("/bracket-city/2026-10-11/game")
    assert response.status_code == 200
    assert response.json() is None
    assert route.calls.last.request.headers["Cookie"] == f"atljwt6={TOKEN}"


@respx.mock
def test_cookies_are_never_sent_to_puzzle_servers():
    route = respx.get(f"{BRACKET_CITY_URL}/2026-10-11.json").mock(
        return_value=httpx.Response(200, json=BRACKET_CITY))
    response = TestClient(main.app, cookies={"atljwt6": TOKEN}).get("/bracket-city/2026-10-11")
    assert response.status_code == 200
    assert "Cookie" not in route.calls.last.request.headers


@respx.mock
def test_missing_puzzle_is_404():
    """CloudFront's 403 for a missing file is a 404 from the API."""
    respx.get(f"{BRACKET_CITY_URL}/2024-01-01.json").mock(return_value=httpx.Response(403))
    response = client.get("/bracket-city/2024-01-01")
    assert response.status_code == 404
    assert response.json()["detail"] == "No Bracket City puzzle for 2024-01-01"


@respx.mock
def test_saved_games_need_a_login():
    """Saved games without cookies are a 401, before any request is made."""
    route = respx.get(GRAPHQL_URL)
    assert client.get("/bracket-city/2026-10-11/game").status_code == 401
    assert not route.called


def test_account_reads_the_cookie():
    response = TestClient(main.app, cookies={"atljwt6": TOKEN}).get("/account")
    assert response.status_code == 200
    assert response.json()["uuid"] == "user-1"


def test_bad_login_cookie_is_401_without_echoing_it():
    response = TestClient(main.app, cookies={"atljwt6": "not-a-jwt"}).get("/account")
    assert response.status_code == 401
    assert "not-a-jwt" not in response.text


def test_create_app_accepts_fastapi_settings():
    """create_app() passes settings through to FastAPI."""
    app = main.create_app(title="My Atlantic API", docs_url=None)
    assert app.title == "My Atlantic API"
    assert TestClient(app).get("/docs").status_code == 404


def test_openapi_lists_every_route_under_a_tag():
    schema = client.get("/openapi.json").json()
    tags = {tag["name"] for tag in schema["tags"]}
    for path, methods in schema["paths"].items():
        assert set(methods) == {"get"}, path  # read-only
        assert set(methods["get"]["tags"]) <= tags, path


@respx.mock
def test_router_mounts_in_your_own_app_with_your_own_client():
    """The router can be mounted under a prefix, with a client using your cookies."""
    app = FastAPI()
    app.include_router(main.router, prefix="/atlantic")
    main.add_exception_handlers(app)
    shared = AsyncAtlanticGamesClient(cookies={"atljwt6": TOKEN})
    app.dependency_overrides[main.get_client] = lambda: shared

    route = respx.get(GRAPHQL_URL).mock(return_value=httpx.Response(200, json={"data": {
        "batchGameStates": {"items": [], "unprocessedKeys": []}}}))
    response = TestClient(app).get("/atlantic/bracket-city/2026-10-11/game")
    assert response.status_code == 200
    assert route.calls.last.request.headers["Cookie"] == f"atljwt6={TOKEN}"

    respx.get(f"{BRACKET_CITY_URL}/2024-01-01.json").mock(return_value=httpx.Response(404))
    assert TestClient(app).get("/atlantic/bracket-city/2024-01-01").status_code == 404


def test_crossword_download(atl):
    import puz
    atl.crossword.return_value = CrosswordPuzzle(**CROSSWORD)
    response = client.get("/crosswords/daily/2026-10-09/download")
    assert response.status_code == 200 and response.headers["content-type"] == "application/x-crossword"
    assert response.headers["content-disposition"] == 'attachment; filename="atlantic-atlantic_20261009.puz"'
    assert puz.load(response.content).solution == "AB"
    atl.crossword.assert_awaited_with(date="2026-10-09", series="daily")
    ipuz = client.get("/crosswords/id/atlantic_20261009/download?series=inferno&format=ipuz")
    assert ipuz.status_code == 200 and ipuz.json()["solution"] == [["A", "B"]]
    atl.crossword.assert_awaited_with(puzzle_id="atlantic_20261009", series="inferno")
    assert client.get("/crosswords/daily/2026-10-09/download?format=pdf").status_code == 422


def test_crossword_download_that_cant_be_exported_is_422(atl):
    from atlgames import AtlanticGamesExportError
    atl.crossword.return_value = CrosswordPuzzle(**CROSSWORD)
    with mock.patch("atlgames.formats.export", side_effect=AtlanticGamesExportError("puz", ["a reason"])):
        response = client.get("/crosswords/id/atlantic_20261009/download")
    assert response.status_code == 422
    assert response.json()["detail"] == {"format": "puz", "reasons": ["a reason"]}
