"""FastAPI app and router for The Atlantic Games API.

Requires the `api` extra::

    pip install "atlantic-games[api]"

Run the ready-made app with ``uvicorn atlgames.api:app``, build your own with
``create_app()``, or mount ``router`` in an existing FastAPI app (then call
``add_exception_handlers()`` on that app too).

The API is read-only: it only fetches puzzles and saved games, and never
changes anything in your Atlantic account.

By default each request is made with the Atlantic login cookies (`atljwt6`
and `atljwt`) sent to the API; other cookies are never passed on. To use other
cookies, such as your own from a secret, override the ``get_client``
dependency with a shared client::

    app = create_app()
    client = AsyncAtlanticGamesClient(cookies=...)
    app.dependency_overrides[get_client] = lambda: client
"""
import datetime
import enum
import math
from typing import Any
from typing import AsyncIterator
from typing import Optional

try:
    from fastapi import APIRouter
    from fastapi import Depends
    from fastapi import FastAPI
    from fastapi import HTTPException
    from fastapi import Path
    from fastapi import Query
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from fastapi.responses import Response
except ImportError as err:  # pragma: no cover
    raise ImportError(
        'atlgames.api requires FastAPI. Install it with: pip install "atlantic-games[api]"'
    ) from err

import httpx

from atlgames import AsyncAtlanticGamesClient
from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesExportError
from atlgames import AtlanticGamesHTTPError
from atlgames import AtlanticGamesNotFoundError
from atlgames import AtlanticGamesParseError
from atlgames import AtlanticGamesRateLimitError
from atlgames import __version__
from atlgames import formats
from atlgames.auth import ENTITLEMENTS_COOKIE
from atlgames.auth import SESSION_COOKIE
from atlgames.auth import Account
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
from atlgames.stats import BracketCityStats
from atlgames.stats import RabbitholeStats
from atlgames.stats import bracket_city_stats
from atlgames.stats import rabbithole_stats

__all__ = ["add_exception_handlers", "app", "create_app", "get_client", "router"]

OPENAPI_TAGS = [
    {"name": "Account", "description": "Who the login cookies belong to"},
    {"name": "Bracket City", "description": "Bracket City puzzles and saved games"},
    {"name": "Crosswords", "description": "The Atlantic Crossword and Caleb's Inferno, from Amuse Labs"},
    {"name": "Games", "description": "The games on The Atlantic's games hub"},
    {"name": "Rabbithole", "description": "Rabbithole puzzles and saved games"},
    {"name": "Stacks", "description": "Stacks puzzles (the game ended on 2026-08-24)"},
    {"name": "Trivia", "description": "Atlantic Trivia (the game ended on 2026-08-14)"},
]

#: The only cookies passed on to The Atlantic.
ATLANTIC_COOKIES = (SESSION_COOKIE, ENTITLEMENTS_COOKIE)

router = APIRouter()


class Series(str, enum.Enum):
    """Crossword series."""
    daily = "daily"
    inferno = "inferno"


def _iso(day: Optional[datetime.date]) -> Optional[str]:
    return day.isoformat() if day else None


async def get_client(request: Request) -> AsyncIterator[AsyncAtlanticGamesClient]:
    """Yield an Atlantic Games client using the Atlantic cookies sent with the request."""
    cookies = {name: request.cookies[name] for name in ATLANTIC_COOKIES if request.cookies.get(name)}
    try:
        client = AsyncAtlanticGamesClient(cookies=cookies)
    except ValueError as err:  # the message never includes cookie values
        raise HTTPException(status_code=400, detail=str(err)) from None
    async with client:
        try:
            _ = client.account  # read the login token now, so a bad one is a 401, not a 500
        except ValueError:
            raise HTTPException(status_code=401, detail="The atljwt6 cookie isn't a valid login token") from None
        yield client


async def atlantic_not_found_handler(request: Request, exc: AtlanticGamesNotFoundError) -> JSONResponse:
    """Return 404 for dates and IDs with no puzzle."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def atlantic_authentication_handler(request: Request,
                                          exc: AtlanticGamesAuthenticationError) -> JSONResponse:
    """Return 401 when the request needs a login cookie that's missing or expired."""
    return JSONResponse(status_code=401, content={"detail": str(exc)})


async def atlantic_rate_limit_handler(request: Request, exc: AtlanticGamesRateLimitError) -> JSONResponse:
    """Return 429, with Retry-After when The Atlantic said how long to wait."""
    headers = {"Retry-After": str(math.ceil(exc.retry_after))} if exc.retry_after is not None else None
    return JSONResponse(status_code=429, content={"detail": str(exc)}, headers=headers)


async def atlantic_http_error_handler(request: Request, exc: AtlanticGamesHTTPError) -> JSONResponse:
    """Return 502 for other errors from The Atlantic or Amuse Labs, including GraphQL errors."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


async def atlantic_parse_error_handler(request: Request, exc: AtlanticGamesParseError) -> JSONResponse:
    """Return 502 when a page or file didn't contain the expected game data."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


async def transport_error_handler(request: Request, exc: httpx.TransportError) -> JSONResponse:
    """Return 502 when The Atlantic or Amuse Labs can't be reached."""
    return JSONResponse(status_code=502, content={"detail": f"Couldn't reach upstream: {type(exc).__name__}"})


def add_exception_handlers(app: FastAPI) -> None:
    """Return Atlantic errors from the client as HTTP responses instead of 500s."""
    app.add_exception_handler(AtlanticGamesNotFoundError, atlantic_not_found_handler)
    app.add_exception_handler(AtlanticGamesAuthenticationError, atlantic_authentication_handler)
    app.add_exception_handler(AtlanticGamesRateLimitError, atlantic_rate_limit_handler)
    app.add_exception_handler(AtlanticGamesHTTPError, atlantic_http_error_handler)
    app.add_exception_handler(AtlanticGamesParseError, atlantic_parse_error_handler)
    app.add_exception_handler(httpx.TransportError, transport_error_handler)


def create_app(**kwargs: Any) -> FastAPI:
    """Return a FastAPI app serving The Atlantic Games API.

    Keyword arguments are passed to FastAPI and override the defaults, for
    example ``create_app(title="My Atlantic API", docs_url=None)``.
    """
    settings = {
        "title": "Atlantic Games API",
        "description": (
            "Unofficial, read-only API for The Atlantic's games, built with "
            "[atlantic-games](https://github.com/lukwam/atlantic-games)."
        ),
        "version": __version__,
        "openapi_tags": OPENAPI_TAGS,
        "license_info": {"name": "MIT", "identifier": "MIT"},
    }
    settings.update(kwargs)
    app = FastAPI(**settings)
    app.include_router(router)
    add_exception_handlers(app)
    return app


# Account
@router.get(
    "/account",
    response_model=Account,
    summary="Get who the login cookies belong to",
    tags=["Account"],
)
async def get_account(client: AsyncAtlanticGamesClient = Depends(get_client)) -> Account:
    """
    **Get the account**

    Returns the Atlantic user ID, token expiry and entitlements read from the
    `atljwt6` and `atljwt` cookies. Makes no request; the cookies aren't
    verified. Returns 401 without the `atljwt6` cookie.
    """
    account = client.account
    if account is None:
        raise HTTPException(status_code=401, detail="No atljwt6 cookie: log in to theatlantic.com")
    return account


# Bracket City
@router.get(
    "/bracket-city/latest",
    response_model=BracketCityPuzzle,
    summary="Get the latest Bracket City puzzle",
    tags=["Bracket City"],
)
async def get_bracket_city_latest(client: AsyncAtlanticGamesClient = Depends(get_client)) -> BracketCityPuzzle:
    """
    **Get the latest Bracket City puzzle**

    Returns the newest published Bracket City puzzle, with its solutions.

    **Backend API**
    ```
    GET https://d2gknrezp32xyk.cloudfront.net/puzzles/index.json
    GET https://d2gknrezp32xyk.cloudfront.net/puzzles/{date}.json
    ```
    """
    return await client.bracket_city()


@router.get(
    "/bracket-city/dates",
    response_model=list[str],
    summary="List every published Bracket City date",
    tags=["Bracket City"],
)
async def list_bracket_city_dates(client: AsyncAtlanticGamesClient = Depends(get_client)) -> list[str]:
    """
    **List Bracket City dates**

    Returns every published Bracket City date, oldest first. The archive
    starts on 2025-01-01.

    **Backend API**
    ```
    GET https://d2gknrezp32xyk.cloudfront.net/puzzles/index.json
    ```
    """
    return await client.bracket_city_dates()


@router.get(
    "/bracket-city/games",
    response_model=list[BracketCityGame],
    summary="List your saved Bracket City games",
    tags=["Bracket City"],
)
async def list_bracket_city_games(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date_start: Optional[datetime.date] = Query(None, examples=["2026-10-01"]),
    date_end: Optional[datetime.date] = Query(None, examples=["2026-10-31"]),
) -> list[BracketCityGame]:
    """
    **List your saved Bracket City games**

    Returns your saved Bracket City games between two dates (default: the
    whole archive), oldest first. Requires the `atljwt6` cookie. Makes one
    request per 25 dates.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (batchGameStates)
    ```
    """
    return await client.bracket_city_games(_iso(date_start), _iso(date_end))


@router.get(
    "/bracket-city/stats",
    response_model=BracketCityStats,
    summary="Get your Bracket City stats",
    tags=["Bracket City"],
)
async def get_bracket_city_stats(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date_start: Optional[datetime.date] = Query(None, examples=["2026-01-01"]),
    date_end: Optional[datetime.date] = Query(None, examples=["2026-12-31"]),
) -> BracketCityStats:
    """
    **Get your Bracket City stats**

    Returns games played and completed, streaks, efficiency, peeks and hints,
    computed from your saved games (The Atlantic has no stats endpoint).
    Requires the `atljwt6` cookie.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (batchGameStates)
    ```
    """
    return bracket_city_stats(await client.bracket_city_games(_iso(date_start), _iso(date_end)))


@router.get(
    "/bracket-city/{date}",
    response_model=BracketCityPuzzle,
    summary="Get the Bracket City puzzle for a specific date",
    tags=["Bracket City"],
)
async def get_bracket_city(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date: datetime.date = Path(..., examples=["2026-10-11"]),
) -> BracketCityPuzzle:
    """
    **Get a Bracket City puzzle**

    Returns the Bracket City puzzle for the date provided in the path
    parameter, with its solutions. Puzzles are available from 2025-01-01.

    **Backend API**
    ```
    GET https://d2gknrezp32xyk.cloudfront.net/puzzles/{date}.json
    ```
    """
    return await client.bracket_city(date.isoformat())


@router.get(
    "/bracket-city/{date}/game",
    response_model=Optional[BracketCityGame],
    summary="Get your saved Bracket City game for a specific date",
    tags=["Bracket City"],
)
async def get_bracket_city_game(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date: datetime.date = Path(..., examples=["2026-10-11"]),
) -> Optional[BracketCityGame]:
    """
    **Get your saved Bracket City game**

    Returns your saved game for the date provided in the path parameter, or
    null if you have none. Requires the `atljwt6` cookie.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (batchGameStates)
    ```
    """
    return await client.bracket_city_game(date.isoformat())


# Crosswords
@router.get(
    "/crosswords/puzzles",
    response_model=list[CrosswordListing],
    summary="List crosswords",
    tags=["Crosswords"],
)
async def list_crosswords(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    series: Series = Query(Series.daily, examples=["daily"]),
    date_start: Optional[datetime.date] = Query(None, examples=["2026-10-01"]),
    date_end: Optional[datetime.date] = Query(None, examples=["2026-10-31"]),
    limit: Optional[int] = Query(None, ge=1, examples=[10]),
) -> list[CrosswordListing]:
    """
    **List crosswords**

    Returns a series' crosswords (daily is The Atlantic Crossword, inferno is
    Caleb's Inferno), newest first, without grids or clues. Puzzle IDs are
    irregular, so use these listings to find them. Makes one request per 500
    puzzles.

    **Backend API**
    ```
    GET https://cdn3.amuselabs.com/atlantic/api/v1/puzzles
    ```
    """
    return await client.crosswords(series.value, _iso(date_start), _iso(date_end), limit)


@router.get(
    "/crosswords/id/{puzzle_id}",
    response_model=CrosswordPuzzle,
    summary="Get a crossword by its puzzle ID",
    tags=["Crosswords"],
)
async def get_crossword_by_id(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    puzzle_id: str = Path(..., examples=["atlantic_20261009"]),
    series: Series = Query(Series.daily, examples=["daily"]),
) -> CrosswordPuzzle:
    """
    **Get a crossword by ID**

    Returns a crossword, with its solution, by its puzzle ID from
    `/crosswords/puzzles`.

    **Backend API**
    ```
    GET https://cdn3.amuselabs.com/atlantic/crossword?id={puzzle_id}&set={series}
    ```
    """
    return await client.crossword(puzzle_id=puzzle_id, series=series.value)


@router.get(
    "/crosswords/id/{puzzle_id}/play",
    response_model=CrosswordPlay,
    summary="Get your saved play of a crossword",
    tags=["Crosswords"],
)
async def get_crossword_play(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    puzzle_id: str = Path(..., examples=["atlantic_20261009"]),
    series: Series = Query(Series.daily, examples=["daily"]),
) -> CrosswordPlay:
    """
    **Get your saved crossword play**

    Returns your progress on a crossword: score, time taken and whether you
    used check, reveal or hints. Requires the `atljwt6` cookie, which is read
    for your user ID (only the ID is sent to Amuse Labs, never the cookie).

    **Backend API**
    ```
    GET https://cdn3.amuselabs.com/atlantic/crossword?id={puzzle_id}&set={series}&uid={user_id}
    ```
    """
    return await client.crossword_play(puzzle_id, series.value)


class ExportFormat(str, enum.Enum):
    """Crossword file format."""
    puz = "puz"
    ipuz = "ipuz"
    xml = "xml"


_DOWNLOAD_RESPONSES = {200: {"content": {media: {} for media in formats.MEDIA_TYPES.values()}},
                       422: {"description": "The puzzle can't be saved in this format"}}


def _download(puzzle: CrosswordPuzzle, file_format: ExportFormat) -> Response:
    try:
        content = formats.export(puzzle, file_format.value)
    except AtlanticGamesExportError as err:
        raise HTTPException(status_code=422, detail={"format": err.format, "reasons": err.reasons}) from None
    filename = f"atlantic-{puzzle.id}.{file_format.value}"
    return Response(content, media_type=formats.MEDIA_TYPES[file_format.value],
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# Registered before /crosswords/{series}/{date}/download, which has the same shape.
@router.get(
    "/crosswords/id/{puzzle_id}/download",
    summary="Download a crossword by ID as a .puz, .ipuz or .xml file",
    tags=["Crosswords"],
    response_class=Response,
    responses=_DOWNLOAD_RESPONSES,
)
async def download_crossword_by_id(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    puzzle_id: str = Path(..., examples=["atlantic_20261010"]),
    series: Series = Query(Series.daily),
    file_format: ExportFormat = Query(ExportFormat.puz, alias="format"),
) -> Response:
    """
    **Download a crossword file by ID**

    Returns the crossword as Across Lite `.puz`, `.ipuz` or Crossword Compiler
    `.xml`. Puzzles these formats can't represent return 422 with the reasons.

    **Backend API**
    ```
    GET https://cdn3.amuselabs.com/atlantic/crossword?id={puzzle_id}&set={series}
    ```
    """
    puzzle = await client.crossword(puzzle_id=puzzle_id, series=series.value)
    return _download(puzzle, file_format)


@router.get(
    "/crosswords/{series}/{date}/download",
    summary="Download a crossword as a .puz, .ipuz or .xml file",
    tags=["Crosswords"],
    response_class=Response,
    responses=_DOWNLOAD_RESPONSES,
)
async def download_crossword(
    series: Series,
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date: datetime.date = Path(..., examples=["2026-10-09"]),
    file_format: ExportFormat = Query(ExportFormat.puz, alias="format"),
) -> Response:
    """
    **Download a crossword file**

    Returns the crossword in the series published on the date provided in the
    path parameter as Across Lite `.puz`, `.ipuz` or Crossword Compiler `.xml`.
    Puzzles these formats can't represent return 422 with the reasons.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (amuseLabsPuzzles)
    GET https://cdn3.amuselabs.com/atlantic/crossword?id={puzzle_id}&set={series}
    ```
    """
    puzzle = await client.crossword(date=date.isoformat(), series=series.value)
    return _download(puzzle, file_format)


@router.get(
    "/crosswords/{series}/latest",
    response_model=CrosswordPuzzle,
    summary="Get the latest crossword in a series",
    tags=["Crosswords"],
)
async def get_crossword_latest(
    series: Series,
    client: AsyncAtlanticGamesClient = Depends(get_client),
) -> CrosswordPuzzle:
    """
    **Get the latest crossword**

    Returns the newest crossword in the series provided in the path
    parameter, with its solution.

    **Backend API**
    ```
    GET https://cdn3.amuselabs.com/atlantic/api/v1/puzzles
    GET https://cdn3.amuselabs.com/atlantic/crossword?id={puzzle_id}&set={series}
    ```
    """
    return await client.crossword(series=series.value)


@router.get(
    "/crosswords/{series}/{date}",
    response_model=CrosswordPuzzle,
    summary="Get the crossword for a specific date",
    tags=["Crosswords"],
)
async def get_crossword(
    series: Series,
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date: datetime.date = Path(..., examples=["2026-10-09"]),
) -> CrosswordPuzzle:
    """
    **Get a crossword**

    Returns the crossword in the series published on the date provided in the
    path parameter (in New York), with its solution.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (amuseLabsPuzzles)
    GET https://cdn3.amuselabs.com/atlantic/crossword?id={puzzle_id}&set={series}
    ```
    """
    return await client.crossword(date=date.isoformat(), series=series.value)


# Games hub
@router.get(
    "/games",
    response_model=list[Game],
    summary="List the games on the games hub",
    tags=["Games"],
)
async def list_games(client: AsyncAtlanticGamesClient = Depends(get_client)) -> list[Game]:
    """
    **List games**

    Returns the games on The Atlantic's games hub.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (gamesHub)
    ```
    """
    return await client.games()


@router.get(
    "/games/{slug}",
    response_model=Game,
    summary="Get a game by slug",
    tags=["Games"],
)
async def get_game(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    slug: str = Path(..., examples=["bracket-city"]),
) -> Game:
    """
    **Get a game**

    Returns a game by its slug, including some no longer on the hub.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (game)
    ```
    """
    return await client.game(slug)


# Rabbithole
@router.get(
    "/rabbithole/latest",
    response_model=RabbitholePuzzle,
    summary="Get the latest Rabbithole puzzle",
    tags=["Rabbithole"],
)
async def get_rabbithole_latest(client: AsyncAtlanticGamesClient = Depends(get_client)) -> RabbitholePuzzle:
    """
    **Get the latest Rabbithole puzzle**

    Returns the newest Rabbithole puzzle, with its questions and answers.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (rabbitholePuzzles)
    ```
    """
    return await client.rabbithole()


@router.get(
    "/rabbithole/puzzles",
    response_model=list[RabbitholePuzzle],
    summary="List Rabbithole puzzles",
    tags=["Rabbithole"],
)
async def list_rabbithole_puzzles(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date_start: Optional[datetime.date] = Query(None, examples=["2026-10-01"]),
    date_end: Optional[datetime.date] = Query(None, examples=["2026-10-31"]),
) -> list[RabbitholePuzzle]:
    """
    **List Rabbithole puzzles**

    Returns every Rabbithole puzzle between two dates (default: all), newest
    first, with their questions and answers. Rabbithole is published on
    weekdays from 2026-08-12.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (rabbitholePuzzles)
    ```
    """
    return await client.rabbithole_puzzles(_iso(date_start), _iso(date_end))


@router.get(
    "/rabbithole/games",
    response_model=list[RabbitholeGame],
    summary="List your saved Rabbithole games",
    tags=["Rabbithole"],
)
async def list_rabbithole_games(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date_start: Optional[datetime.date] = Query(None, examples=["2026-10-01"]),
    date_end: Optional[datetime.date] = Query(None, examples=["2026-10-31"]),
) -> list[RabbitholeGame]:
    """
    **List your saved Rabbithole games**

    Returns your saved Rabbithole games between two dates (default: all),
    oldest first. Requires the `atljwt6` cookie.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (rabbitholePuzzles, batchGameStates)
    ```
    """
    return await client.rabbithole_games(_iso(date_start), _iso(date_end))


@router.get(
    "/rabbithole/stats",
    response_model=RabbitholeStats,
    summary="Get your Rabbithole stats",
    tags=["Rabbithole"],
)
async def get_rabbithole_stats(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date_start: Optional[datetime.date] = Query(None, examples=["2026-08-12"]),
    date_end: Optional[datetime.date] = Query(None, examples=["2026-12-31"]),
) -> RabbitholeStats:
    """
    **Get your Rabbithole stats**

    Returns games played and completed, scores and question results, computed
    from your saved games. Requires the `atljwt6` cookie.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (rabbitholePuzzles, batchGameStates)
    ```
    """
    return rabbithole_stats(await client.rabbithole_games(_iso(date_start), _iso(date_end)))


@router.get(
    "/rabbithole/{puzzle_id}",
    response_model=RabbitholePuzzle,
    summary="Get a Rabbithole puzzle by ID",
    tags=["Rabbithole"],
)
async def get_rabbithole(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    puzzle_id: str = Path(..., examples=["42"]),
) -> RabbitholePuzzle:
    """
    **Get a Rabbithole puzzle**

    Returns the Rabbithole puzzle with the ID provided in the path parameter,
    with its questions and answers. IDs aren't in date order; find them with
    `/rabbithole/puzzles`.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (rabbitholePuzzle)
    ```
    """
    return await client.rabbithole(puzzle_id)


@router.get(
    "/rabbithole/{puzzle_id}/game",
    response_model=Optional[RabbitholeGame],
    summary="Get your saved game for a Rabbithole puzzle",
    tags=["Rabbithole"],
)
async def get_rabbithole_game(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    puzzle_id: str = Path(..., examples=["42"]),
) -> Optional[RabbitholeGame]:
    """
    **Get your saved Rabbithole game**

    Returns your saved game for the puzzle ID provided in the path parameter,
    or null if you have none. Requires the `atljwt6` cookie.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (rabbitholePuzzle, batchGameStates)
    ```
    """
    return await client.rabbithole_game(puzzle_id)


# Stacks
@router.get(
    "/stacks",
    response_model=list[StacksPuzzle],
    summary="List every Stacks puzzle",
    tags=["Stacks"],
)
async def list_stacks(client: AsyncAtlanticGamesClient = Depends(get_client)) -> list[StacksPuzzle]:
    """
    **List Stacks puzzles**

    Returns every Stacks puzzle (2025-06-17 to 2026-08-24) with its solution,
    read from the game's script.

    **Backend API**
    ```
    GET https://stacks.games.theatlantic.com/?view=tnf
    ```
    """
    return await client.stacks_puzzles()


@router.get(
    "/stacks/{date}",
    response_model=StacksPuzzle,
    summary="Get the Stacks puzzle for a specific date",
    tags=["Stacks"],
)
async def get_stacks(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    date: datetime.date = Path(..., examples=["2026-08-24"]),
) -> StacksPuzzle:
    """
    **Get a Stacks puzzle**

    Returns the Stacks puzzle for the date provided in the path parameter,
    with its solution. Puzzles are available from 2025-06-17 to 2026-08-24.

    **Backend API**
    ```
    GET https://stacks.games.theatlantic.com/?view=tnf
    ```
    """
    return await client.stacks(date.isoformat())


# Trivia
@router.get(
    "/trivia",
    response_model=list[TriviaArticle],
    summary="List Atlantic Trivia articles",
    tags=["Trivia"],
)
async def list_trivia(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    limit: Optional[int] = Query(None, ge=1, examples=[10]),
) -> list[TriviaArticle]:
    """
    **List Trivia articles**

    Returns Atlantic Trivia articles, newest first, without questions. Trivia
    ended on 2026-08-14; daily articles with questions start on 2026-03-13
    and older entries are weekly newsletter roundups.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (collection river)
    ```
    """
    return await client.trivia_articles(limit)


@router.get(
    "/trivia/{article_id}",
    response_model=TriviaArticle,
    summary="Get a day's Trivia questions",
    tags=["Trivia"],
)
async def get_trivia(
    client: AsyncAtlanticGamesClient = Depends(get_client),
    article_id: str = Path(..., pattern=r"^\d+$", examples=["688280"]),
) -> TriviaArticle:
    """
    **Get a Trivia article**

    Returns a day's Trivia questions and answers, by the article ID from
    `/trivia`.

    **Backend API**
    ```
    GET https://graphql.theatlantic.com/ (article)
    ```
    """
    return await client.trivia(article_id)


app = create_app()
