"""Client tests, end to end over mocked HTTP.

Every test runs against both AtlanticGamesClient and
AsyncAtlanticGamesClient, so they run offline and need no cookies.
"""
import copy
import datetime
import json

import httpx
import pytest
import respx

import atlgames
from atlgames import AsyncAtlanticGamesClient
from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesClient
from atlgames import AtlanticGamesHTTPError
from atlgames import AtlanticGamesNotFoundError
from atlgames import AtlanticGamesParseError
from atlgames import amuse
from atlgames import client as client_module
from atlgames.models import BracketCityGame
from atlgames.models import BracketCityPuzzle
from atlgames.models import CrosswordPuzzle
from atlgames.models import RabbitholeGame
from atlgames.models import RabbitholePuzzle
from atlgames.transport import GRAPHQL_URL
from tests.support import USER_UUID
from tests.support import Api
from tests.support import b64json
from tests.support import bracket_city_puzzle
from tests.support import cookies
from tests.support import crossword_page
from tests.support import crossword_params
from tests.support import load
from tests.support import text

BC = "https://d2gknrezp32xyk.cloudfront.net/puzzles"
AMUSE = "https://cdn3.amuselabs.com/atlantic"
STACKS = "https://stacks.games.theatlantic.com/"


@pytest.fixture(params=["sync", "async"])
def make(request):
    """Make a sync or async client."""
    return lambda **kwargs: Api(request.param, **kwargs)


@pytest.fixture
def api(make):
    return make()


@pytest.fixture
def logged_in(make):
    return make(cookies=cookies())


@pytest.fixture
def mock():
    with respx.mock(assert_all_called=False) as router:
        yield router
    # The library is read-only: every request any client test makes must be a
    # GET, and no GraphQL query may be a mutation.
    for call in router.calls:
        assert call.request.method == "GET", call.request
        query = call.request.url.params.get("query", "")
        assert not query.lstrip().startswith("mutation"), query


class GraphQL:
    """Answers GraphQL requests with a handler(query, variables) and keeps them."""

    def __init__(self, router, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []
        router.get(GRAPHQL_URL).mock(side_effect=self._respond)

    def _respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = request.url.params
        variables = json.loads(params["variables"]) if "variables" in params else {}
        result = self.handler(params["query"], variables)
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)

    @property
    def queries(self) -> list[str]:
        return [r.url.params["query"] for r in self.requests]

    @property
    def variables(self) -> list[dict]:
        return [json.loads(r.url.params.get("variables", "{}")) for r in self.requests]


def no_cookies(route):
    for call in route.calls:
        assert "Cookie" not in call.request.headers, call.request.url


# Bracket City

async def test_bracket_city(api, mock):
    route = mock.get(f"{BC}/2026-10-08.json").respond(json=bracket_city_puzzle("2026-10-08"))
    puzzle = await api("bracket_city", "2026-10-08")
    assert isinstance(puzzle, BracketCityPuzzle)
    assert puzzle.solved_text == "Raytheon patents the microwave" and puzzle.author == "Ben Gross"
    assert route.call_count == 1
    headers = route.calls.last.request.headers
    assert headers["User-Agent"].startswith(f"atlantic-games/{atlgames.__version__}")


async def test_bracket_city_takes_a_date(api, mock):
    route = mock.get(f"{BC}/2026-10-08.json").respond(json=bracket_city_puzzle("2026-10-08"))
    await api("bracket_city", datetime.date(2026, 10, 8))
    assert route.called


async def test_bracket_city_latest(api, mock):
    index = load("bracket_city/index.json")
    mock.get(f"{BC}/index.json").respond(json=list(reversed(index)))
    route = mock.get(f"{BC}/2026-10-11.json").respond(json=bracket_city_puzzle("2026-10-11"))
    assert (await api("bracket_city")).puzzleDate == "2026-10-11"
    assert route.called


async def test_bracket_city_dates(api, mock):
    mock.get(f"{BC}/index.json").respond(json=["2025-01-02", "2025-01-01"])
    assert await api("bracket_city_dates") == ["2025-01-01", "2025-01-02"]


async def test_bracket_city_future_date_is_not_found(make, mock):
    """CloudFront answers 403 for puzzles that aren't published yet; cookies never go there."""
    route = mock.get(f"{BC}/2026-10-12.json").respond(403, text="<Error>AccessDenied</Error>")
    with pytest.raises(AtlanticGamesNotFoundError, match="No Bracket City puzzle for 2026-10-12"):
        await make(cookies=cookies())("bracket_city", "2026-10-12")
    assert route.call_count == 1
    no_cookies(route)


def state_item(slug: str, date: str, game_id: str, progress: str = "complete", **state) -> dict:
    return {"gameKey": f"{date}:{slug}:{game_id}", "gameSlug": slug, "gameDate": date, "gameId": game_id,
            "progress": progress, "gameState": state, "updatedAt": 1791500000000,
            "createdAt": "2026-10-11T12:00:00Z", "userUUID": USER_UUID}


async def test_bracket_city_games_are_fetched_25_at_a_time(logged_in, mock):
    dates = [(datetime.date(2026, 8, 1) + datetime.timedelta(days=i)).isoformat() for i in range(60)]
    index = mock.get(f"{BC}/index.json").respond(json=dates)

    def handler(query, variables):
        assert "batchGameStates" in query
        items = [state_item(k["gameSlug"], k["gameDate"], k["gameId"]) for k in variables["items"]
                 if k["gameDate"].endswith("5")]
        return {"data": {"batchGameStates": {"items": items, "unprocessedKeys": []}}}

    graph = GraphQL(mock, handler)
    games = await logged_in("bracket_city_games")
    assert [len(v["items"]) for v in graph.variables] == [25, 25, 10]
    assert graph.variables[0]["items"][0] == {"gameSlug": "bracket-city", "gameDate": "2026-08-01", "gameId": "v1"}
    assert [g.gameDate for g in games] == [d for d in dates if d.endswith("5")]
    assert all(isinstance(g, BracketCityGame) for g in games)
    assert all(g.fetched_at and g.fetched_at.tzinfo for g in games)
    # The login cookie goes to The Atlantic's API only.
    assert all(r.headers["Cookie"].startswith("atljwt6=") for r in graph.requests)
    no_cookies(index)


async def test_bracket_city_games_between_dates(logged_in, mock):
    mock.get(f"{BC}/index.json").respond(json=["2026-10-09", "2026-10-10", "2026-10-11", "2026-10-08"])
    graph = GraphQL(mock, lambda q, v: {"data": {"batchGameStates": {"items": [], "unprocessedKeys": None}}})
    assert await logged_in("bracket_city_games", "2026-10-09", "2026-10-10") == []
    assert [k["gameDate"] for k in graph.variables[0]["items"]] == ["2026-10-09", "2026-10-10"]


async def test_bracket_city_game(logged_in, mock):
    saved = load("graphql/batch_game_states.json")["data"]["batchGameStates"]["items"][0]
    graph = GraphQL(mock, lambda q, v: {"data": {"batchGameStates": {"items": [saved], "unprocessedKeys": []}}})
    game = await logged_in("bracket_city_game", "2026-10-08")
    assert graph.variables == [{"items": [{"gameSlug": "bracket-city", "gameDate": "2026-10-08", "gameId": "v1"}]}]
    assert isinstance(game, BracketCityGame) and game.complete and game.userUUID == USER_UUID
    puzzle = BracketCityPuzzle(**bracket_city_puzzle("2026-10-08"))
    assert game.solved_fraction(puzzle) == 1.0 and game.efficiency == 0.8


async def test_bracket_city_game_not_saved(logged_in, mock):
    GraphQL(mock, lambda q, v: {"data": {"batchGameStates": {"items": [], "unprocessedKeys": []}}})
    assert await logged_in("bracket_city_game", "2026-10-08") is None


@pytest.mark.parametrize("method,args", [
    ("bracket_city_game", ("2026-10-08",)),
    ("bracket_city_games", ()),
    ("game_states", ([("bracket-city", "2026-10-08", "v1")],)),
    ("game_state", ("bracket-city", "2026-10-08", "v1")),
    ("rabbithole_game", (RabbitholePuzzle(id="53", publishedAt="2026-10-09T04:00:00Z"),)),
    ("crossword_play", ("atlantic_20261010",)),
])
async def test_saved_games_need_a_login(api, mock, method, args):
    mock.get(f"{BC}/index.json").respond(json=["2026-10-08"])
    graph = GraphQL(mock, lambda q, v: pytest.fail("no GraphQL request expected"))
    with pytest.raises(AtlanticGamesAuthenticationError, match="logged in"):
        await api(method, *args)
    assert graph.requests == []


async def test_expired_login_is_an_authentication_error(logged_in, mock):
    body = {"errors": [{"message": "Bad request", "path": ["batchGameStates"],
                        "extensions": {"http": {"status": 400}, "code": "BAD_REQUEST"}}], "data": None}
    GraphQL(mock, lambda q, v: body)
    with pytest.raises(AtlanticGamesAuthenticationError, match="missing or expired"):
        await logged_in("game_state", "bracket-city", "2026-10-08", "v1")


async def test_game_states_retries_unprocessed_keys(logged_in, mock):
    keys = [("bracket-city", "2026-10-10", "v1"), ("rabbithole", "2026-10-09", 53),
            ("bracket-city", "2026-10-08", "v1")]
    calls = []

    def handler(query, variables):
        calls.append(variables["items"])
        items = variables["items"]
        if len(calls) == 1:
            # The first answer has one game and leaves two for later.
            return {"data": {"batchGameStates": {"items": [state_item(**_key(items[0]))],
                                                 "unprocessedKeys": items[1:]}}}
        return {"data": {"batchGameStates": {"items": [state_item(**_key(i)) for i in items],
                                             "unprocessedKeys": []}}}

    GraphQL(mock, handler)
    states = await logged_in("game_states", keys + [keys[0]])  # duplicates are asked for once
    assert [len(c) for c in calls] == [3, 2]
    assert calls[0][1] == {"gameSlug": "rabbithole", "gameDate": "2026-10-09", "gameId": "53"}
    # In date order, with each game's model.
    assert [(s.gameDate, type(s)) for s in states] == [
        ("2026-10-08", BracketCityGame), ("2026-10-09", RabbitholeGame), ("2026-10-10", BracketCityGame)]


async def test_game_states_gives_up_on_unprocessed_keys(logged_in, mock):
    calls = []

    def handler(query, variables):
        calls.append(1)
        return {"data": {"batchGameStates": {"items": [], "unprocessedKeys": variables["items"]}}}

    GraphQL(mock, handler)
    with pytest.raises(AtlanticGamesHTTPError, match="didn't return 1 saved games"):
        await logged_in("game_states", [("bracket-city", "2026-10-08", "v1")])
    assert len(calls) == 3


async def test_game_states_without_keys(logged_in, mock):
    graph = GraphQL(mock, lambda q, v: pytest.fail("no request expected"))
    assert await logged_in("game_states", []) == []
    assert graph.requests == []


def _key(item: dict) -> dict:
    return {"slug": item["gameSlug"], "date": item["gameDate"], "game_id": item["gameId"]}


async def test_saved_games_fixture(logged_in, mock):
    body = load("graphql/batch_game_states.json")
    GraphQL(mock, lambda q, v: body)
    states = await logged_in("game_states", [("bracket-city", "2026-10-08", "v1")])
    assert [s.gameSlug for s in states].count("rabbithole") == 1
    assert [s.progress.value for s in states] == ["complete", "complete", "complete", "inProgress", "notStarted"]


# Crosswords

def listing_page(items: list[dict], has_more: bool, series: str = "atlantic") -> dict:
    return {"status": 0, "seriesToPuzzleMetadata": {series: items}, "hasMore": has_more}


def listings(count: int, start: datetime.date = datetime.date(2026, 10, 11)) -> list[dict]:
    """Made-up daily listings, newest first, published at 12:01am in New York."""
    template = load("crossword/list.json")["seriesToPuzzleMetadata"]["atlantic"][0]
    result = []
    for i in range(count):
        day = start - datetime.timedelta(days=i)
        published = datetime.datetime.combine(day, datetime.time(0, 1), client_module.EASTERN)
        result.append({**template, "puzzleId": f"atlantic_{day:%Y%m%d}",
                       "publicationTime": int(published.timestamp() * 1000)})
    return result


@pytest.fixture
def date_picker(mock):
    return mock.get(f"{AMUSE}/date-picker").respond(text=text("crossword/date_picker.html"))


def token() -> str:
    return amuse.load_token(text("crossword/date_picker.html"))


async def test_crosswords(make, mock, date_picker):
    route = mock.get(f"{AMUSE}/api/v1/puzzles").respond(json=load("crossword/list.json") | {"hasMore": False})
    api = make(cookies=cookies())
    found = await api("crosswords")
    assert [x.puzzleId for x in found[:2]] == ["atlantic_20261011", "atlantic_20261010"]
    assert found[0].series == "atlantic" and found[0].date == "2026-10-11"
    assert dict(route.calls.last.request.url.params) == {
        "loadToken": token(), "series": "atlantic", "limit": "500", "offset": "0"}
    assert dict(date_picker.calls.last.request.url.params) == {"set": "atlantic"}
    # The token is reused, and no cookies go to Amuse Labs.
    await api("crosswords", "inferno")
    assert date_picker.call_count == 1
    assert route.calls.last.request.url.params["series"] == "atlantic-inferno"
    no_cookies(route)
    no_cookies(date_picker)


async def test_crosswords_pages(api, mock, date_picker):
    everything = listings(1200)

    def page(request):
        offset, size = int(request.url.params["offset"]), int(request.url.params["limit"])
        return httpx.Response(200, json=listing_page(everything[offset:offset + size],
                                                     offset + size < len(everything)))

    route = mock.get(f"{AMUSE}/api/v1/puzzles").mock(side_effect=page)
    found = await api("crosswords")
    assert len(found) == 1200 and found[-1].puzzleId == everything[-1]["puzzleId"]
    assert [c.request.url.params["offset"] for c in route.calls] == ["0", "500", "1000"]


async def test_crosswords_limit(api, mock, date_picker):
    everything = listings(100)

    def page(request):
        offset, size = int(request.url.params["offset"]), int(request.url.params["limit"])
        return httpx.Response(200, json=listing_page(everything[offset:offset + size], True))

    route = mock.get(f"{AMUSE}/api/v1/puzzles").mock(side_effect=page)
    found = await api("crosswords", limit=3)
    assert [x.puzzleId for x in found] == ["atlantic_20261011", "atlantic_20261010", "atlantic_20261009"]
    assert route.call_count == 1 and route.calls.last.request.url.params["limit"] == "23"


async def test_crosswords_between_dates(api, mock, date_picker):
    everything = listings(1000)

    def page(request):
        offset, size = int(request.url.params["offset"]), int(request.url.params["limit"])
        return httpx.Response(200, json=listing_page(everything[offset:offset + size], True))

    route = mock.get(f"{AMUSE}/api/v1/puzzles").mock(side_effect=page)
    found = await api("crosswords", date_start="2026-10-01", date_end="2026-10-03")
    assert [x.date for x in found] == ["2026-10-03", "2026-10-02", "2026-10-01"]
    assert route.call_count == 1  # stops once it's past the start date


async def test_crosswords_stale_token(api, mock, date_picker):
    stale = load("crossword/list_error.json")
    route = mock.get(f"{AMUSE}/api/v1/puzzles").mock(side_effect=[
        httpx.Response(200, json=stale), httpx.Response(200, json=listing_page(listings(2), False))])
    assert len(await api("crosswords")) == 2
    assert date_picker.call_count == 2 and route.call_count == 2


async def test_crosswords_stale_token_twice(api, mock, date_picker):
    mock.get(f"{AMUSE}/api/v1/puzzles").respond(json=load("crossword/list_error.json"))
    with pytest.raises(AtlanticGamesParseError, match="You do not have access"):
        await api("crosswords")
    assert date_picker.call_count == 2


async def test_crosswords_error(api, mock, date_picker):
    mock.get(f"{AMUSE}/api/v1/puzzles").respond(json={"status": 1, "errorMessage": "Broken"})
    with pytest.raises(AtlanticGamesParseError, match="Broken"):
        await api("crosswords")


async def test_crosswords_unknown_series(api):
    with pytest.raises(ValueError):
        await api("crosswords", "weekly")


@pytest.fixture
def puzzle_page(mock):
    return mock.get(f"{AMUSE}/crossword").respond(text=text("crossword/atlantic_20261010.html"))


async def test_crossword_by_id(make, mock, puzzle_page):
    puzzle = await make(cookies=cookies())("crossword", puzzle_id="atlantic_20261010")
    assert isinstance(puzzle, CrosswordPuzzle)
    assert puzzle.id == "atlantic_20261010" and puzzle.series == "atlantic" and puzzle.date == "2026-10-10"
    assert puzzle.grid()[0][2] == "J"
    assert dict(puzzle_page.calls.last.request.url.params) == {"id": "atlantic_20261010", "set": "atlantic"}
    no_cookies(puzzle_page)


async def test_crossword_inferno(api, mock):
    route = mock.get(f"{AMUSE}/crossword").respond(text=text("crossword/inferno_20260517.html"))
    puzzle = await api("crossword", puzzle_id="inferno_20260517", series="inferno")
    assert puzzle.series == "atlantic-inferno" and (puzzle.w, puzzle.h) == (7, 25)
    assert route.calls.last.request.url.params["set"] == "atlantic-inferno"


async def test_crossword_by_date(api, mock, puzzle_page):
    def handler(query, variables):
        assert "amuseLabsPuzzles" in query
        return {"data": {"amuseLabsPuzzles": [
            {"puzzleId": "atlantic_20261009", "publicationDateTime": "2026-10-09T04:01:00Z"},
            {"puzzleId": "atlantic_20261010", "publicationDateTime": "2026-10-10T04:01:00Z", "title": "Saturday"}]}}

    graph = GraphQL(mock, handler)
    puzzle = await api("crossword", "2026-10-10")
    assert puzzle.id == "atlantic_20261010"
    # Midnight to midnight in New York.
    assert graph.variables == [{"series": "atlantic", "from": "2026-10-10T04:00:00Z", "to": "2026-10-11T04:00:00Z"}]
    assert puzzle_page.calls.last.request.url.params["id"] == "atlantic_20261010"


async def test_crossword_by_date_in_winter(api, mock, puzzle_page):
    # 00:01 in New York is 05:01 UTC in winter.
    graph = GraphQL(mock, lambda q, v: {"data": {"amuseLabsPuzzles": [
        {"puzzleId": "atlantic_20261010", "publicationDateTime": "2026-01-15T05:01:00Z"}]}})
    await api("crossword", datetime.date(2026, 1, 15))
    assert graph.variables[0]["from"] == "2026-01-15T05:00:00Z"


async def test_crossword_by_date_not_found(api, mock):
    GraphQL(mock, lambda q, v: {"data": {"amuseLabsPuzzles": []}})
    with pytest.raises(AtlanticGamesNotFoundError, match="No daily crossword for 2026-10-12"):
        await api("crossword", "2026-10-12")


async def test_latest_crossword(api, mock, date_picker, puzzle_page):
    mock.get(f"{AMUSE}/api/v1/puzzles").respond(json=listing_page(listings(1, datetime.date(2026, 10, 10)), True))
    assert (await api("crossword")).id == "atlantic_20261010"


async def test_latest_crossword_none(api, mock, date_picker):
    mock.get(f"{AMUSE}/api/v1/puzzles").respond(json=listing_page([], False, "atlantic-inferno"))
    with pytest.raises(AtlanticGamesNotFoundError, match="No crosswords in inferno"):
        await api("crossword", series="inferno")


@pytest.mark.parametrize("page", [text("crossword/error.html"), "<html><title>Saturday</title></html>"])
async def test_unpublished_crossword(api, mock, page):
    """PuzzleMe answers unpublished puzzles with HTTP 200 and an error page."""
    mock.get(f"{AMUSE}/crossword").respond(text=page)
    with pytest.raises(AtlanticGamesNotFoundError, match="no crossword atlantic_20261012"):
        await api("crossword", puzzle_id="atlantic_20261012")


async def test_crossword_rereads_the_scramble_from_c_min_js(make, mock, puzzle_page):
    """When Amuse Labs changes its scramble, the client reads the new one from its JS."""
    script = mock.get(f"{AMUSE}/b67da0d/js/c-min.js").respond(text=text("crossword/c-min-Vf.js"))
    api = make()
    api.client._passes = ((0, 40, (9, 7)),)  # outdated
    puzzle = await api("crossword", puzzle_id="atlantic_20261010")
    assert puzzle.id == "atlantic_20261010"
    assert api.client._passes == amuse.SCRAMBLE_PASSES
    assert script.call_count == 1
    no_cookies(script)
    await api("crossword", puzzle_id="atlantic_20261010")
    assert script.call_count == 1


async def test_crossword_scramble_changed_without_version(api, mock):
    params = crossword_params("atlantic_20261010")
    del params["resourceVersionDir"]
    mock.get(f"{AMUSE}/crossword").respond(text=crossword_page(params))
    api.client._passes = ((0, 40, (9, 7)),)
    with pytest.raises(AtlanticGamesParseError, match="changed its encoding"):
        await api("crossword", puzzle_id="atlantic_20261010")


async def test_crossword_scramble_unreadable(api, mock, puzzle_page):
    mock.get(f"{AMUSE}/b67da0d/js/c-min.js").respond(text="function nothing(){}")
    api.client._passes = ((0, 40, (9, 7)),)
    with pytest.raises(AtlanticGamesParseError, match="unscramble function"):
        await api("crossword", puzzle_id="atlantic_20261010")


async def test_crossword_play(make, mock):
    params = crossword_params("atlantic_20261010")
    params["rawp"] = b64json({"id": "atlantic_20261010", "series": "atlantic", "userId": USER_UUID, "playState": 2,
                              "timeTaken": 312, "nCorrectEntries": 28, "updatedTimestamp": 1791650000000,
                              "nPrints": 0})
    route = mock.get(f"{AMUSE}/crossword").respond(text=crossword_page(params))
    play = await make(cookies=cookies())("crossword_play", "atlantic_20261010")
    assert play.puzzleId == "atlantic_20261010" and play.userId == USER_UUID
    assert play.started and play.timeTaken == 312 and play.series == "atlantic"
    # Amuse Labs keys plays by the Atlantic user ID; the cookies stay home.
    assert dict(route.calls.last.request.url.params) == {"id": "atlantic_20261010", "set": "atlantic",
                                                         "uid": USER_UUID}
    no_cookies(route)


async def test_crossword_play_without_saved_play(logged_in, mock):
    params = crossword_params("atlantic_20261010")
    params["rawp"] = ""
    mock.get(f"{AMUSE}/crossword").respond(text=crossword_page(params))
    play = await logged_in("crossword_play", "inferno_20260517", "inferno")
    assert play.puzzleId == "inferno_20260517" and play.series == "atlantic-inferno" and not play.started


# Rabbithole

def rabbithole_result() -> dict:
    return load("graphql/rabbithole_latest.json")["data"]["rabbitholePuzzles"]["results"][0]


async def test_latest_rabbithole(api, mock):
    graph = GraphQL(mock, lambda q, v: load("graphql/rabbithole_latest.json"))
    puzzle = await api("rabbithole")
    assert puzzle.id == "53" and puzzle.date == "2026-10-09" and len(puzzle.questions) == 7
    assert "page:1,pageSize:1" in graph.queries[0]
    assert "Cookie" not in graph.requests[0].headers


async def test_rabbithole_by_id(api, mock):
    graph = GraphQL(mock, lambda q, v: {"data": {"rabbitholePuzzle": rabbithole_result()}})
    assert (await api("rabbithole", 53)).byline == "Drew Goins"
    assert graph.variables == [{"id": "53"}]


async def test_rabbithole_not_found(api, mock):
    GraphQL(mock, lambda q, v: {"errors": [{"message": "404: Not Found", "extensions": {
        "response": {"status": 404, "body": {"detail": "No Puzzle matches the given query."}}}}], "data": None})
    with pytest.raises(AtlanticGamesNotFoundError, match="No Rabbithole puzzle 999"):
        await api("rabbithole", 999)


async def test_no_rabbithole_puzzles(api, mock):
    GraphQL(mock, lambda q, v: {"data": {"rabbitholePuzzles": {"results": []}}})
    with pytest.raises(AtlanticGamesNotFoundError):
        await api("rabbithole")


def rabbithole_pages(count: int):
    puzzles = []
    for i in range(count):
        puzzle = copy.deepcopy(rabbithole_result())
        puzzle["id"] = str(count - i)
        puzzles.append(puzzle)

    def handler(query, variables):
        page = variables["page"]
        results = puzzles[(page - 1) * 100:page * 100]
        return {"data": {"rabbitholePuzzles": {"count": count, "results": results,
                                               "next": "more" if page * 100 < count else None}}}
    return handler


async def test_rabbithole_puzzles(api, mock):
    graph = GraphQL(mock, rabbithole_pages(150))
    puzzles = await api("rabbithole_puzzles", "2026-08-12", "2026-10-09")
    assert len(puzzles) == 150 and puzzles[0].id == "150"
    assert graph.variables == [{"page": 1, "start": "2026-08-12", "end": "2026-10-09"},
                               {"page": 2, "start": "2026-08-12", "end": "2026-10-09"}]


async def test_rabbithole_games(logged_in, mock):
    pages = rabbithole_pages(2)

    def handler(query, variables):
        if "batchGameStates" in query:
            assert variables["items"] == [{"gameSlug": "rabbithole", "gameDate": "2026-10-09", "gameId": "2"},
                                          {"gameSlug": "rabbithole", "gameDate": "2026-10-09", "gameId": "1"}]
            return {"data": {"batchGameStates": {"items": [state_item("rabbithole", "2026-10-09", "2", score=21)],
                                                 "unprocessedKeys": []}}}
        return pages(query, variables)

    graph = GraphQL(mock, handler)
    games = await logged_in("rabbithole_games")
    assert len(games) == 1 and isinstance(games[0], RabbitholeGame) and games[0].data.score == 21
    assert ["Cookie" in r.headers for r in graph.requests] == [False, True]


async def test_rabbithole_game(logged_in, mock):
    def handler(query, variables):
        if "rabbitholePuzzle(" in query:
            return {"data": {"rabbitholePuzzle": rabbithole_result()}}
        assert variables["items"] == [{"gameSlug": "rabbithole", "gameDate": "2026-10-09", "gameId": "53"}]
        return {"data": {"batchGameStates": {"items": [], "unprocessedKeys": []}}}

    graph = GraphQL(mock, handler)
    assert await logged_in("rabbithole_game", "53") is None
    assert len(graph.requests) == 2
    assert await logged_in("rabbithole_game", RabbitholePuzzle(**rabbithole_result())) is None
    assert len(graph.requests) == 3


# Trivia

def trivia_node(n: int) -> dict:
    return {"id": f"BlogArticle:{688000 + n}", "title": f"Trivia {n}",
            "url": f"https://www.theatlantic.com/newsletters/2026/08/trivia/{688000 + n}/",
            "datePublished": "2026-08-14T10:00:00Z"}


def trivia_river(total: int):
    def handler(query, variables):
        start = int(variables.get("after", "0"))
        nodes = [{"node": trivia_node(n)} for n in range(start, min(start + 40, total))]
        nodes.append({"node": None})
        return {"data": {"collection": {"river": {
            "pageInfo": {"hasNextPage": start + 40 < total, "endCursor": str(start + 40)}, "edges": nodes}}}}
    return handler


async def test_trivia_articles(api, mock):
    graph = GraphQL(mock, trivia_river(90))
    articles = await api("trivia_articles")
    assert len(articles) == 90 and articles[0].article_id == "688000"
    # The river 404s on a null `after`, so the first page doesn't send one.
    assert "after" not in graph.queries[0] and "variables" not in graph.requests[0].url.params
    assert "river(first:40)" in graph.queries[0]
    assert "$after" in graph.queries[1] and graph.variables[1:] == [{"after": "40"}, {"after": "80"}]


async def test_trivia_articles_limit(api, mock):
    graph = GraphQL(mock, trivia_river(90))
    assert len(await api("trivia_articles", limit=45)) == 45
    assert len(graph.requests) == 2


@pytest.mark.parametrize("article", [
    "688280", 688280, "BlogArticle:688280",
    "https://www.theatlantic.com/newsletters/2026/08/atlantic-trivia-last-call/688280/",
])
async def test_trivia(api, mock, article):
    def handler(query, variables):
        return {"data": {"article": {**trivia_node(280), "content": [
            {"__typename": "ArticleParagraph"},
            {"__typename": "ArticleInlineTrivia", "questions": [
                {"id": "1", "questionText": "<p>Q1?</p>", "canonicalAnswer": "A1", "topicText": "History"},
                {"id": "2", "questionText": "Q2?", "canonicalAnswer": "A2"}]},
            {"__typename": "ArticleInlineTrivia", "questions": None}]}}}

    graph = GraphQL(mock, handler)
    trivia = await api("trivia", article)
    assert graph.variables == [{"id": "688280"}]
    assert [q.question for q in trivia.questions] == ["Q1?", "Q2?"]
    assert trivia.questions[0].accepts("a1") and trivia.date == "2026-08-14"
    assert "content" not in trivia.model_dump()


async def test_trivia_from_a_listing(api, mock):
    graph = GraphQL(mock, lambda q, v: {"data": {"article": {**trivia_node(5), "content": None}}})
    listing = atlgames.models.TriviaArticle(**trivia_node(5))
    assert (await api("trivia", listing)).questions == []
    assert graph.variables == [{"id": "688005"}]


async def test_trivia_not_found(api, mock):
    GraphQL(mock, lambda q, v: {"data": {"article": None}})
    with pytest.raises(AtlanticGamesNotFoundError, match="No article 1"):
        await api("trivia", 1)


async def test_trivia_bad_id(api):
    with pytest.raises(ValueError, match="Not an Atlantic article"):
        await api("trivia", "https://www.theatlantic.com/games/")


# Stacks

@pytest.fixture
def stacks_site(mock):
    page = mock.get(STACKS).respond(text=text("stacks/page.html"))
    script = mock.get(f"{STACKS}_next/static/chunks/app/page-f3bdd79621bb6f9e.js").respond(
        text=text("stacks/page-f3bdd79621bb6f9e.js"))
    return page, script


async def test_stacks_puzzles_are_fetched_once(make, stacks_site):
    page, script = stacks_site
    api = make(cookies=cookies())
    puzzles = await api("stacks_puzzles")
    assert len(puzzles) == 40 and puzzles[0].date == "2025-06-17" and puzzles[1].id == 0
    assert dict(page.calls.last.request.url.params) == {"view": "tnf"}
    puzzles.clear()  # callers get their own list
    assert (await api("stacks", "2025-06-18")).wordStrings == ["AGLEAM", "COWBOY", "OUTSET", "SPADE"]
    assert len(await api("stacks_puzzles")) == 40
    assert page.call_count == script.call_count == 1
    no_cookies(page)
    no_cookies(script)


@pytest.mark.parametrize("date", ["2025-06-16", "2026-08-25", "2026-08-24", "not a date"])
async def test_stacks_not_found(api, stacks_site, date):
    """Outside the archive, or past the puzzles in the (trimmed) script."""
    with pytest.raises(AtlanticGamesNotFoundError):
        await api("stacks", date)


# Games hub

async def test_games(api, mock):
    graph = GraphQL(mock, lambda q, v: {"data": {"gamesHub": [
        {"name": "Bracket City", "slug": "bracket-city", "hasArchive": True, "lightModeColor": "#fff"}]}})
    games = await api("games")
    assert games[0].slug == "bracket-city" and games[0].model_dump()["lightModeColor"] == "#fff"
    assert "gamesHub" in graph.queries[0]


async def test_game(api, mock):
    graph = GraphQL(mock, lambda q, v: {"data": {"game": {"name": "Stacks", "slug": "stacks"}}})
    assert (await api("game", "stacks")).name == "Stacks"
    assert graph.variables == [{"slug": "stacks"}]


async def test_unknown_game(api, mock):
    GraphQL(mock, lambda q, v: {"errors": [{"message": "404: Not Found", "extensions": {
        "code": "INTERNAL_SERVER_ERROR", "response": {"status": 404}}}], "data": None})
    with pytest.raises(AtlanticGamesNotFoundError, match="No game nope"):
        await api("game", "nope")


# Clients

def test_sync_and_async_clients_have_the_same_methods():
    sync = {n for n in dir(AtlanticGamesClient) if not n.startswith("_") and callable(getattr(AtlanticGamesClient, n))}
    async_ = {n for n in dir(AsyncAtlanticGamesClient)
              if not n.startswith("_") and callable(getattr(AsyncAtlanticGamesClient, n))}
    assert sync - {"close"} == async_ - {"aclose"}
    assert AtlanticGamesClient.bracket_city.__doc__ == AsyncAtlanticGamesClient.bracket_city.__doc__
    assert "Bracket City" in AtlanticGamesClient.bracket_city.__doc__


def test_sync_client_lifecycle():
    with AtlanticGamesClient() as client:
        http = client._http
    assert http.is_closed
    own = httpx.Client()
    with AtlanticGamesClient(http_client=own) as client:
        assert client._http is own
    assert not own.is_closed  # yours to close
    own.close()


async def test_async_client_lifecycle():
    async with AsyncAtlanticGamesClient() as client:
        http = client._http
    assert http.is_closed
    own = httpx.AsyncClient()
    async with AsyncAtlanticGamesClient(http_client=own):
        pass
    assert not own.is_closed
    await own.aclose()


async def test_custom_user_agent(make, mock):
    route = mock.get(f"{BC}/index.json").respond(json=[])
    await make(user_agent="my-bot/1.0")("bracket_city_dates")
    assert route.calls.last.request.headers["User-Agent"] == "my-bot/1.0"


async def test_game_state(logged_in, mock):
    item = state_item("new-game", "2026-10-10", "7", "inProgress", level=3)
    graph = GraphQL(mock, lambda q, v: {"data": {"batchGameStates": {"items": [item], "unprocessedKeys": []}}})
    state = await logged_in("game_state", "new-game", "2026-10-10", 7)
    assert type(state) is atlgames.models.GameState and state.gameState == {"level": 3}
    assert graph.variables == [{"items": [{"gameSlug": "new-game", "gameDate": "2026-10-10", "gameId": "7"}]}]


def test_export_error_lists_reasons():
    error = atlgames.AtlanticGamesExportError("puz", ["rebus squares", "a 30x30 grid"])
    assert str(error) == "Can't export to puz: rebus squares; a 30x30 grid"
    assert error.format == "puz" and error.reasons == ["rebus squares", "a 30x30 grid"]
    assert isinstance(error, ValueError)


async def test_crossword_by_date_ignores_neighbouring_days(api, mock):
    GraphQL(mock, lambda q, v: {"data": {"amuseLabsPuzzles": [
        {"puzzleId": "atlantic_20261011", "publicationDateTime": "2026-10-11T04:01:00Z"}]}})
    with pytest.raises(AtlanticGamesNotFoundError, match="No daily crossword for 2026-10-10"):
        await api("crossword", "2026-10-10")


async def test_crosswords_rejects_a_limit_below_one(api, mock):
    with pytest.raises(ValueError, match="at least 1"):
        await api("crosswords", limit=0)


async def test_bracket_city_games_takes_dates(logged_in, mock):
    mock.get(f"{BC}/index.json").respond(json=["2026-10-09", "2026-10-10", "2026-10-11"])
    graph = GraphQL(mock, lambda q, v: {"data": {"batchGameStates": {"items": [], "unprocessedKeys": []}}})
    await logged_in("bracket_city_games", datetime.date(2026, 10, 10), datetime.date(2026, 10, 11))
    assert [i["gameDate"] for i in graph.variables[0]["items"]] == ["2026-10-10", "2026-10-11"]
