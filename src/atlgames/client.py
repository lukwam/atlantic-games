"""Atlantic Games clients.

`AtlanticGamesClient` is synchronous and `AsyncAtlanticGamesClient` is its
asyncio twin: same methods, same arguments, same results, but awaited. Both
run the operations defined once in `_Operations`.
"""
import datetime
import functools
import inspect
import re
from typing import Any
from typing import Iterable

import httpx

from atlgames import __version__
from atlgames import amuse
from atlgames import stacks as stacks_game
from atlgames.auth import Account
from atlgames.auth import Cookies
from atlgames.auth import account_from_cookies
from atlgames.auth import parse_cookies
from atlgames.exceptions import AtlanticGamesAuthenticationError
from atlgames.exceptions import AtlanticGamesHTTPError
from atlgames.exceptions import AtlanticGamesNotFoundError
from atlgames.exceptions import AtlanticGamesParseError
from atlgames.models import EASTERN
from atlgames.models import STATE_MODELS
from atlgames.models import BracketCityGame
from atlgames.models import BracketCityPuzzle
from atlgames.models import CrosswordListing
from atlgames.models import CrosswordPlay
from atlgames.models import CrosswordPuzzle
from atlgames.models import CrosswordSeries
from atlgames.models import Game
from atlgames.models import GameState
from atlgames.models import RabbitholeGame
from atlgames.models import RabbitholePuzzle
from atlgames.models import StacksPuzzle
from atlgames.models import TriviaArticle
from atlgames.models import parse
from atlgames.models import parse_list
from atlgames.transport import Request
from atlgames.transport import Settings
from atlgames.transport import graphql
from atlgames.transport import run_async
from atlgames.transport import run_sync

BRACKET_CITY_URL = "https://d2gknrezp32xyk.cloudfront.net/puzzles"
USER_AGENT = f"atlantic-games/{__version__} (+https://github.com/lukwam/atlantic-games)"
#: Saved games per batchGameStates request.
STATE_BATCH = 25
#: Crosswords per Amuse Labs list request.
CROSSWORD_PAGE = 500
#: Trivia articles per request (The Atlantic rejects much more).
TRIVIA_PAGE = 40

GameKey = tuple[str, str, str]

_RABBITHOLE_FIELDS = """
  id publishedAt status byline recirculationBlurb
  article { id url title }
  questions { id questionText canonicalAnswer validAnswers targetAccuracy hintText choices }
"""
_STATE_FIELDS = "gameKey gameSlug gameDate gameId progress gameState updatedAt createdAt userUUID"
_GAME_FIELDS = ("name slug description shortDescription url iconUrl hasArchive author "
                "isFeaturedGame archiveDescription lightModeColor darkModeColor ribbonText")


def _date(value: str | datetime.date) -> datetime.date:
    return datetime.date.fromisoformat(value) if isinstance(value, str) else value


def _eastern_midnight(day: datetime.date) -> str:
    start = datetime.datetime.combine(day, datetime.time(), EASTERN)
    return start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _article_id(article: Any) -> str:
    """Return the numeric ID from an ID, "BlogArticle:688280", a URL or a listing."""
    if isinstance(article, TriviaArticle):
        return article.article_id
    text = str(article)
    match = re.search(r"/(\d+)/?$", text) or re.search(r"(\d+)$", text)
    if not match:
        raise ValueError(f"Not an Atlantic article ID or URL: {article!r}")
    return match.group(1)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _field(data: Any, *path: str, kind: type = dict) -> Any:
    """Return `data[path[0]][path[1]]...`, checking the response has each
    step and that the result is a `kind`.

    Raises AtlanticGamesParseError naming the path, never the response's
    values, if it doesn't.
    """
    value = data
    for depth, key in enumerate(path, 1):
        if not isinstance(value, dict) or key not in value:
            raise AtlanticGamesParseError(f"The response had no {'.'.join(path[:depth])}")
        value = value[key]
    if not isinstance(value, kind):
        raise AtlanticGamesParseError(f"The response's {'.'.join(path)} wasn't a {kind.__name__}")
    return value


class _Operations:
    """Every request the clients make, as generators (see transport.py)."""

    def __init__(self, cookies: Cookies = None, user_agent: str = USER_AGENT,
                 retries: int = 3, backoff: float = 0.5):
        self._settings = Settings(parse_cookies(cookies), user_agent, retries, backoff)
        self._load_token: str | None = None
        self._passes = amuse.SCRAMBLE_PASSES
        self._stacks: list[StacksPuzzle] | None = None

    @property
    def account(self) -> Account | None:
        """Who you're logged in as, read from your cookies (no request).
        None without the `atljwt6` cookie."""
        return account_from_cookies(self._settings.cookies)

    def _require_account(self) -> Account:
        account = self.account
        if account is None:
            raise AtlanticGamesAuthenticationError(
                "This needs you to be logged in: pass cookies with atljwt6 from theatlantic.com")
        return account

    # Bracket City

    def bracket_city_dates(self) -> list[str]:
        """Return every published Bracket City date (YYYY-MM-DD), oldest first.

        The Atlantic's archive starts on 2025-01-01. Future puzzles aren't
        available until they're published.
        """
        dates = yield Request(f"{BRACKET_CITY_URL}/index.json")
        if not isinstance(dates, list) or not all(isinstance(d, str) for d in dates):
            raise AtlanticGamesParseError("Bracket City's list of dates wasn't a list of dates")
        return sorted(dates)

    def bracket_city(self, date: str | None = None) -> BracketCityPuzzle:
        """Return the Bracket City puzzle for a date, or the latest one."""
        if date is None:
            dates = yield from _Operations.bracket_city_dates(self)
            date = dates[-1]
        data = yield Request(f"{BRACKET_CITY_URL}/{_date(date).isoformat()}.json",
                             not_found=f"No Bracket City puzzle for {date}")
        return parse(BracketCityPuzzle, data)

    def bracket_city_game(self, date: str) -> BracketCityGame | None:
        """Return your saved Bracket City game for a date, or None.

        Needs cookies. Games played in the app only reach your account once
        you open them while logged in.
        """
        states = yield from _Operations.game_states(self, [("bracket-city", _date(date).isoformat(), "v1")])
        return states[0] if states else None

    def bracket_city_games(self, date_start: str | None = None,
                           date_end: str | None = None) -> list[BracketCityGame]:
        """Return your saved Bracket City games between two dates (default:
        the whole archive), oldest first. Needs cookies. Makes one request
        per 25 dates, plus one for the list of dates."""
        start = _date(date_start).isoformat() if date_start else None
        end = _date(date_end).isoformat() if date_end else None
        dates = yield from _Operations.bracket_city_dates(self)
        dates = [d for d in dates if (not start or d >= start) and (not end or d <= end)]
        return (yield from _Operations.game_states(self, [("bracket-city", d, "v1") for d in dates]))

    # Crosswords

    def _token(self):
        if self._load_token is None:
            html = yield Request(f"{amuse.AMUSE_URL}/date-picker", {"set": CrosswordSeries.daily.value},
                                 kind="text")
            self._load_token = amuse.load_token(html)
        return self._load_token

    def crosswords(self, series: CrosswordSeries | str = CrosswordSeries.daily,
                   date_start: str | None = None, date_end: str | None = None,
                   limit: int | None = None) -> list[CrosswordListing]:
        """Return a series' crosswords, newest first.

        `series` is daily (the Crossword, from 2018) or inferno (Caleb's
        Inferno). Filters by publication date in New York. Puzzle IDs are
        irregular (some have typos or are hex), so use these listings rather
        than building IDs from dates. Makes one request per 500 puzzles.
        """
        series = CrosswordSeries.coerce(series)
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        date_start = _date(date_start).isoformat() if date_start else None
        date_end = _date(date_end).isoformat() if date_end else None
        token = yield from self._token()
        found: list[CrosswordListing] = []
        offset = 0
        refreshed = False
        while True:
            page_size = CROSSWORD_PAGE if limit is None else min(CROSSWORD_PAGE, limit - len(found) + 20)
            body = yield Request(f"{amuse.AMUSE_URL}/api/v1/puzzles", {
                "loadToken": token, "series": series.value, "limit": page_size, "offset": offset})
            if not isinstance(body, dict):
                raise AtlanticGamesParseError("Amuse Labs' puzzle list wasn't a JSON object")
            if body.get("status") not in (0, None):
                # A stale token: get a new one, once.
                if (body.get("errorDetails") or {}).get("errorCode") == 84 and not refreshed:
                    refreshed = True
                    self._load_token = None
                    token = yield from self._token()
                    continue
                raise AtlanticGamesParseError(f"Amuse Labs' puzzle list failed: {body.get('errorMessage')}")
            series_items = body.get("seriesToPuzzleMetadata") or {}
            items = _field(series_items, series.value, kind=list) if series.value in series_items else []
            reached_start = False
            for item in items:
                listing = parse(CrosswordListing, item, series=series.value)
                if date_end and listing.date and listing.date > date_end:
                    continue
                if date_start and listing.date and listing.date < date_start:
                    reached_start = True
                    continue
                found.append(listing)
            offset += len(items)
            if not body.get("hasMore") or not items or reached_start or (limit and len(found) >= limit):
                return found[:limit] if limit else found

    def crossword(self, date: str | None = None, puzzle_id: str | None = None,
                  series: CrosswordSeries | str = CrosswordSeries.daily) -> CrosswordPuzzle:
        """Return a crossword with its solution.

        Give a `puzzle_id` (from crosswords()), a `date`, or neither for the
        latest. Raises AtlanticGamesNotFoundError for dates without a puzzle.
        """
        series = CrosswordSeries.coerce(series)
        if puzzle_id is None:
            puzzle_id = yield from self._crossword_id(series, date)
        html = yield Request(f"{amuse.AMUSE_URL}/crossword", {"id": puzzle_id, "set": series.value}, kind="text")
        params = yield from self._crossword_params(html, puzzle_id)
        data = yield from self._decode(params)
        return parse(CrosswordPuzzle, data, series=series.value)

    def _crossword_id(self, series: CrosswordSeries, date: str | None):
        if date is None:
            latest = yield from _Operations.crosswords(self, series, limit=1)
            if not latest:
                raise AtlanticGamesNotFoundError(f"No crosswords in {series.name}")
            return latest[0].puzzleId
        day = _date(date)
        data = yield graphql(
            "query($series:String!,$from:DateTime!,$to:DateTime!){amuseLabsPuzzles("
            "series:$series,from:$from,to:$to){puzzleId title author puzzleType gridWidth gridHeight "
            "publicationDateTime}}",
            {"series": series.value, "from": _eastern_midnight(day),
             "to": _eastern_midnight(day + datetime.timedelta(days=1))})
        listings = parse_list(CrosswordListing, data.get("amuseLabsPuzzles") or [])
        matching = [item for item in listings if item.date == day.isoformat()]
        if not matching:
            raise AtlanticGamesNotFoundError(f"No {series.name} crossword for {day}")
        return matching[0].puzzleId

    def _crossword_params(self, html: str, puzzle_id: str):
        if amuse.is_error_page(html) or "rawc" not in html:
            raise AtlanticGamesNotFoundError(f"Amuse Labs has no crossword {puzzle_id} (or it's unpublished)")
        return amuse.page_params(html)
        yield  # pragma: no cover  (makes this a generator)

    def _decode(self, params: dict):
        try:
            return amuse.decode_rawc(params["rawc"], self._passes)
        except AtlanticGamesParseError:
            version = params.get("resourceVersionDir")
            if not version:
                raise
        js = yield Request(f"{amuse.AMUSE_URL}/{version}/js/c-min.js", kind="text")
        self._passes = amuse.passes_from_js(js)
        return amuse.decode_rawc(params["rawc"], self._passes)

    def crossword_play(self, puzzle_id: str,
                       series: CrosswordSeries | str = CrosswordSeries.daily) -> CrosswordPlay:
        """Return your saved play of a crossword. Needs cookies.

        Amuse Labs keeps crossword progress itself, keyed by your Atlantic
        user ID, which is read from your cookies.
        """
        account = self._require_account()
        series = CrosswordSeries.coerce(series)
        html = yield Request(f"{amuse.AMUSE_URL}/crossword",
                             {"id": puzzle_id, "set": series.value, "uid": account.uuid}, kind="text")
        params = yield from self._crossword_params(html, puzzle_id)
        play = amuse.decode_field(params, "rawp") or {}
        if not isinstance(play, dict):
            raise AtlanticGamesParseError("Amuse Labs' saved play wasn't a JSON object")
        return parse(CrosswordPlay, {"id": puzzle_id, "series": series.value, **play})

    # Rabbithole

    def rabbithole(self, puzzle_id: int | str | None = None) -> RabbitholePuzzle:
        """Return a Rabbithole puzzle by ID, or the latest one. Rabbithole is
        published on weekdays, from 2026-08-12; IDs aren't in date order."""
        if puzzle_id is None:
            data = yield graphql("{rabbitholePuzzles(page:1,pageSize:1){results{%s}}}" % _RABBITHOLE_FIELDS)
            results = parse_list(RabbitholePuzzle, _field(data, "rabbitholePuzzles", "results", kind=object))
            if not results:
                raise AtlanticGamesNotFoundError("No Rabbithole puzzles")
            return results[0]
        data = yield graphql("query($id:ID!){rabbitholePuzzle(id:$id){%s}}" % _RABBITHOLE_FIELDS,
                             {"id": str(puzzle_id)}, not_found=f"No Rabbithole puzzle {puzzle_id}")
        return parse(RabbitholePuzzle, _field(data, "rabbitholePuzzle", kind=object))

    def rabbithole_puzzles(self, date_start: str | None = None,
                           date_end: str | None = None) -> list[RabbitholePuzzle]:
        """Return every Rabbithole puzzle between two dates (default: all),
        newest first, with their questions and answers."""
        puzzles, page = [], 1
        while True:
            data = yield graphql(
                "query($page:Int,$start:String,$end:String){rabbitholePuzzles(page:$page,pageSize:100,"
                "startDate:$start,endDate:$end){count next results{%s}}}" % _RABBITHOLE_FIELDS,
                {"page": page, "start": date_start, "end": date_end})
            result = _field(data, "rabbitholePuzzles")
            results = parse_list(RabbitholePuzzle, _field(result, "results", kind=object))
            puzzles.extend(results)
            if not result.get("next") or not results:
                return puzzles
            page += 1

    def rabbithole_game(self, puzzle: RabbitholePuzzle | int | str) -> RabbitholeGame | None:
        """Return your saved game for a Rabbithole puzzle, or None. Needs
        cookies. Fetches the puzzle first if you give only its ID."""
        if not isinstance(puzzle, RabbitholePuzzle):
            puzzle = yield from _Operations.rabbithole(self, puzzle)
        states = yield from _Operations.game_states(self, [("rabbithole", puzzle.date, puzzle.id)])
        return states[0] if states else None

    def rabbithole_games(self, date_start: str | None = None,
                         date_end: str | None = None) -> list[RabbitholeGame]:
        """Return your saved Rabbithole games between two dates (default:
        all), oldest first. Needs cookies."""
        puzzles = yield from _Operations.rabbithole_puzzles(self, date_start, date_end)
        return (yield from _Operations.game_states(self, [("rabbithole", p.date, p.id) for p in puzzles]))

    # Trivia

    def trivia_articles(self, limit: int | None = None) -> list[TriviaArticle]:
        """Return Atlantic Trivia articles, newest first, without questions.

        Trivia ended on 2026-08-14. Daily articles with structured questions
        start on 2026-03-13; older entries are weekly newsletter roundups.
        """
        found, after = [], None
        while True:
            # The river 404s on a null `after` and 400s above about 40 per page.
            data = yield graphql(
                "query%s{collection(slug:\"atlantic-trivia\",type:\"category\"){"
                "river(first:%d%s){pageInfo{hasNextPage endCursor} "
                "edges{node{... on Article{id title url datePublished}}}}}}"
                % ("($after:String)" if after else "", TRIVIA_PAGE, ",after:$after" if after else ""),
                {"after": after} if after else None)
            river = _field(data, "collection", "river")
            edges = _field(river, "edges", kind=list)
            if not all(isinstance(edge, dict) for edge in edges):
                raise AtlanticGamesParseError("The response's collection.river.edges weren't objects")
            # Entries that aren't articles come back as empty or null nodes.
            found.extend(parse(TriviaArticle, edge["node"]) for edge in edges if edge.get("node"))
            if limit and len(found) >= limit:
                return found[:limit]
            page_info = _field(river, "pageInfo")
            if not page_info.get("hasNextPage"):
                return found
            after = page_info.get("endCursor")

    def trivia(self, article: TriviaArticle | int | str) -> TriviaArticle:
        """Return a day's Trivia questions and answers, from its article ID,
        URL or listing."""
        article_id = _article_id(article)
        data = yield graphql(
            "query($id:ID!){article(id:$id){id title url datePublished content{__typename "
            "... on ArticleInlineTrivia{questions{id questionText canonicalAnswer validAnswers hintText "
            "subtext topicText targetAccuracy relatedArticle{id url title}}}}}}",
            {"id": article_id}, not_found=f"No article {article_id}")
        if not data.get("article"):
            raise AtlanticGamesNotFoundError(f"No article {article_id}")
        node = _field(data, "article")
        blocks = node.get("content") or []
        if not isinstance(blocks, list) or not all(isinstance(block, dict) for block in blocks):
            raise AtlanticGamesParseError("The response's article.content wasn't a list of blocks")
        questions = [q for block in blocks
                     if block.get("__typename") == "ArticleInlineTrivia" for q in block.get("questions") or []]
        node = {k: v for k, v in node.items() if k != "content"}
        return parse(TriviaArticle, node, questions=questions)

    # Stacks

    def stacks_puzzles(self) -> list[StacksPuzzle]:
        """Return every Stacks puzzle (2025-06-17 to 2026-08-24) with its
        solution. Stacks has ended; the puzzles come from the game's script,
        fetched once per client."""
        if self._stacks is None:
            html = yield Request(stacks_game.STACKS_URL, {"view": "tnf"}, kind="text")
            js = yield Request(stacks_game.page_script_url(html), kind="text")
            self._stacks = [parse(StacksPuzzle, puzzle, date=stacks_game.date_of(i))
                            for i, puzzle in enumerate(stacks_game.puzzles_from_script(js))]
        return list(self._stacks)

    def stacks(self, date: str) -> StacksPuzzle:
        """Return the Stacks puzzle for a date (2025-06-17 to 2026-08-24)."""
        puzzles = yield from _Operations.stacks_puzzles(self)
        try:
            return puzzles[stacks_game.puzzle_index(date)]
        except (ValueError, IndexError) as error:
            raise AtlanticGamesNotFoundError(str(error)) from None

    # Games hub

    def games(self) -> list[Game]:
        """Return the games on The Atlantic's games hub."""
        data = yield graphql("{gamesHub{%s}}" % _GAME_FIELDS)
        return parse_list(Game, _field(data, "gamesHub", kind=object))

    def game(self, slug: str) -> Game:
        """Return a game by slug, including some no longer on the hub."""
        data = yield graphql("query($slug:String!){game(slug:$slug){%s}}" % _GAME_FIELDS,
                             {"slug": slug}, not_found=f"No game {slug}")
        return parse(Game, _field(data, "game", kind=object))

    # Saved games

    def game_state(self, game_slug: str, game_date: str, game_id: str) -> GameState | None:
        """Return a saved game, or None if there's none. Needs cookies."""
        states = yield from _Operations.game_states(self, [(game_slug, game_date, str(game_id))])
        return states[0] if states else None

    def game_states(self, keys: Iterable[GameKey]) -> list[GameState]:
        """Return your saved games for (game slug, date, game ID) keys, in
        date order, skipping games you have no save for. Needs cookies.

        Keys: Bracket City is ("bracket-city", date, "v1"); Rabbithole is
        ("rabbithole", publish date, puzzle ID).
        """
        self._require_account()
        keys = list(dict.fromkeys((s, d, str(i)) for s, d, i in keys))
        states: list[GameState] = []
        for start in range(0, len(keys), STATE_BATCH):
            items = [{"gameSlug": s, "gameDate": d, "gameId": i} for s, d, i in keys[start:start + STATE_BATCH]]
            pending = items
            for _ in range(3):
                data = yield graphql(
                    "query($items:[BatchGetGameStateItem!]!){batchGameStates(items:$items){"
                    "items{%s} unprocessedKeys{gameSlug gameDate gameId}}}" % _STATE_FIELDS,
                    {"items": pending}, auth=True)
                result = _field(data, "batchGameStates")
                fetched = _now()
                for item in _field(result, "items", kind=list):
                    slug = item.get("gameSlug") if isinstance(item, dict) else None
                    states.append(parse(STATE_MODELS.get(slug, GameState), item, fetched_at=fetched))
                pending = result.get("unprocessedKeys") or []
                if not pending:
                    break
            else:
                # Dropping them would look like games you never played.
                raise AtlanticGamesHTTPError(
                    f"The Atlantic didn't return {len(pending)} saved games after 3 tries; try again later")
        return sorted(states, key=lambda s: (s.gameDate, s.gameSlug, s.gameId))


def _sync_method(name: str, op):
    @functools.wraps(op)
    def method(self, *args, **kwargs):
        return run_sync(self._http, self._settings, op(self, *args, **kwargs))
    return method


def _async_method(name: str, op):
    @functools.wraps(op)
    async def method(self, *args, **kwargs):
        return await run_async(self._http, self._settings, op(self, *args, **kwargs))
    return method


def _public_operations():
    for name, value in vars(_Operations).items():
        if not name.startswith("_") and inspect.isgeneratorfunction(value):
            yield name, value


class AtlanticGamesClient(_Operations):
    """Client for The Atlantic's games.

    Puzzles need no login. Your saved games need your Atlantic cookies
    (`atljwt6`, from a logged-in theatlantic.com session), given in any form
    `parse_cookies` accepts. Cookies are only ever sent to The Atlantic's
    GraphQL API, never to Amuse Labs or the puzzle file servers.

    Failed connections, rate limits (429) and server errors are retried up
    to `retries` times with exponential backoff, honoring Retry-After. Pass
    your own `httpx.Client` as `http_client` to control transport details;
    it's used as is and not closed by `close()`.
    """

    def __init__(self, cookies: Cookies = None, http_client: httpx.Client | None = None,
                 timeout: float = 30, user_agent: str = USER_AGENT, retries: int = 3,
                 backoff: float = 0.5):
        super().__init__(cookies, user_agent, retries, backoff)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class AsyncAtlanticGamesClient(_Operations):
    """Asyncio client for The Atlantic's games: the same methods as
    `AtlanticGamesClient`, awaited.

        async with AsyncAtlanticGamesClient() as client:
            puzzle = await client.bracket_city("2026-10-11")
    """

    def __init__(self, cookies: Cookies = None, http_client: httpx.AsyncClient | None = None,
                 timeout: float = 30, user_agent: str = USER_AGENT, retries: int = 3,
                 backoff: float = 0.5):
        super().__init__(cookies, user_agent, retries, backoff)
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()


for _name, _op in list(_public_operations()):
    setattr(AtlanticGamesClient, _name, _sync_method(_name, _op))
    setattr(AsyncAtlanticGamesClient, _name, _async_method(_name, _op))
