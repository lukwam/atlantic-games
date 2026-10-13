"""atlg-mcp: an MCP server for The Atlantic's games, for coding agents and other MCP clients.

Requires the `mcp` extra::

    pip install "atlantic-games[mcp]"
    claude mcp add atlantic-games -- atlg-mcp

Runs locally over stdio. Cookies come from ATLANTIC_COOKIES or your atlg profile
(``atlg auth login``), the same as atlg; they are never returned or logged.
Every tool is read-only: the server only reads puzzles and saved games, and
never saves game state.
"""
import datetime
import functools
import logging
import os
import re
from pathlib import Path
from typing import Any
from typing import Literal

from atlgames import AsyncAtlanticGamesClient
from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesGraphQLError
from atlgames import AtlanticGamesHTTPError
from atlgames import AtlanticGamesNotFoundError
from atlgames import AtlanticGamesParseError
from atlgames import AtlanticGamesRateLimitError
from atlgames import __version__
from atlgames import formats
from atlgames import stats as game_stats
from atlgames import views
from atlgames.files import write_file
from atlgames.models import EASTERN
from atlgames.models import BracketCityPuzzle
from atlgames.models import CrosswordPuzzle
from atlgames.models import normalize_answer
from atlgames.models import strip_html

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp_types import ToolAnnotations
except ImportError as err:  # pragma: no cover
    raise ImportError('atlg-mcp needs the mcp extra. Install it with: pip install "atlantic-games[mcp]"',
                      name=err.name) from err

INSTRUCTIONS = """\
Tools for The Atlantic's games: Bracket City, the Atlantic Crossword, Caleb's
Inferno (a harder crossword), Rabbithole, and the archives of Atlantic
Trivia and Stacks (both ended in August 2026), plus the user's own saved
games and stats.

Dates are YYYY-MM-DD, "today", "yesterday" or a weekday name, in New York time.

Spoilers: puzzle tools hide answers unless include_answers is true. Leave it
false when the user is still solving (for example when they ask for a hint),
and set it to true only when they want the answers. To check a guess without
revealing anything, use the check_* tools; bracket_city_peek gives one clue's
first letter (or its whole answer) like the game's peek. Rabbithole questions
mention the previous answer, so rabbithole only shows the questions up to the
one being solved.

The user's own data (saved games, progress, history and stats) needs their
Atlantic login cookie, atljwt6. If a tool says cookies are missing or expired,
tell the user to run `atlg auth login` or set ATLANTIC_COOKIES.
"""

COOKIE_HELP = ("They can run `atlg auth login` (with atljwt6 from a logged-in theatlantic.com session) "
               "or set ATLANTIC_COOKIES in the MCP server's environment.")
Series = Literal["daily", "inferno"]
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
# Destructive: with overwrite, it replaces an existing file.
WRITES_FILE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

server = MCPServer(name="atlantic-games", version=__version__, instructions=INSTRUCTIONS)
# The client and httpx log every request; keep the server's log to warnings and errors.
logging.getLogger("atlgames").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


def cookies() -> str | None:
    """Return the cookies atlg would use: ATLANTIC_COOKIES, then the active atlg profile."""
    if os.environ.get("ATLANTIC_COOKIES"):
        return os.environ["ATLANTIC_COOKIES"]
    try:
        from atlgames.cli.config import Config
    except ImportError:  # pragma: no cover  (profiles need the cli extra)
        return None
    config = Config()
    return config.get(os.environ.get("ATLG_PROFILE") or config.active_profile, "cookies")


def client() -> AsyncAtlanticGamesClient:
    """Return a client with the user's cookies, if they have any."""
    return AsyncAtlanticGamesClient(cookies=cookies())


def today() -> datetime.date:
    """Today in New York, which is when The Atlantic's puzzles change."""
    return datetime.datetime.now(EASTERN).date()


def day(value: str) -> datetime.date:
    text = value.strip().lower()
    now = today()
    if text == "today":
        return now
    if text == "yesterday":
        return now - datetime.timedelta(days=1)
    if text in WEEKDAYS:
        return now - datetime.timedelta(days=(now.weekday() - WEEKDAYS.index(text)) % 7)
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ToolError(f"Invalid date {value!r}: use YYYY-MM-DD, today, yesterday or a weekday") from None


def optional_day(value: str | None) -> str | None:
    return day(value).isoformat() if value else None


def window(date_start: str | None, date_end: str | None, days: int | None = 30) -> tuple[str | None, str]:
    """Return (start, end) dates; start defaults to `days` before end, or None for no limit."""
    last = day(date_end) if date_end else today()
    if date_start:
        first = day(date_start)
    elif days:
        first = last - datetime.timedelta(days=days - 1)
    else:
        return None, last.isoformat()
    if first > last:
        raise ToolError("date_start is after date_end")
    return first.isoformat(), last.isoformat()


def atlantic_errors(fn):
    """Turn Atlantic Games errors into tool errors with messages an agent can act on."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except AtlanticGamesAuthenticationError:
            raise ToolError("The Atlantic rejected the request: this needs the user's Atlantic login cookie, "
                            "which is missing or has expired (it lasts 30 days). " + COOKIE_HELP) from None
        except AtlanticGamesNotFoundError as err:
            raise ToolError(f"Not found: {err}") from None
        except AtlanticGamesRateLimitError as err:
            wait = f" Try again in {err.retry_after:g} seconds." if err.retry_after else " Try again later."
            raise ToolError("The Atlantic is rate limiting requests." + wait) from None
        except AtlanticGamesGraphQLError as err:
            raise ToolError(f"The Atlantic's API returned an error: {err}") from None
        except AtlanticGamesHTTPError as err:
            raise ToolError(f"The Atlantic returned an error (HTTP {err.status_code or 'unknown'}).") from None
        except AtlanticGamesParseError as err:
            raise ToolError(f"Couldn't read the game data: {err}") from None
        except ValueError as err:
            # Cookie and argument errors; their messages never include cookie values.
            raise ToolError(str(err)) from None
    return wrapper


def tool(annotations=READ_ONLY):
    def decorator(fn):
        return server.tool(annotations=annotations)(atlantic_errors(fn))
    return decorator


def same_answer(guess: str, answer: str) -> bool:
    return normalize_answer(guess) == normalize_answer(answer)


def letters(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


# Bracket City


def clue_number(puzzle: BracketCityPuzzle, clue: int | str) -> int:
    """Return a clue's number (from 1) from its number (as a number or digits) or its text."""
    clues = puzzle.clues()
    if isinstance(clue, str) and clue.strip().isdigit():
        clue = int(clue.strip())
    if isinstance(clue, int):
        if 1 <= clue <= len(clues):
            return clue
        raise ToolError(f"No clue {clue}: this puzzle's clues are numbered 1 to {len(clues)}")
    text = clue.strip().strip("[]").strip().casefold()
    for c in clues:
        if text in (c.text.casefold(), c.raw.casefold()):
            return c.index + 1
    raise ToolError(f"No clue {clue!r} in this puzzle; use a clue number from bracket_city")


@tool()
async def bracket_city(
    date: str | None = None,
    solved: list[int | str] | None = None,
    use_saved_progress: bool = False,
    include_answers: bool = False,
) -> dict[str, Any]:
    """Get a Bracket City puzzle (daily from 2025-01-01; default the latest): the text with its
    nested [bracketed] clues and the clues that can be solved now (every clue inside them solved).

    solved lists clues the user has already solved, by number (from 1) or clue text; their answers
    are filled into the text. use_saved_progress fills in the clues solved in the user's saved game
    (needs cookies). The answers are only included with include_answers; to help without spoiling,
    use check_bracket_city_answer or bracket_city_peek.
    """
    async with client() as atl:
        puzzle = await atl.bracket_city(optional_day(date))
        saved = await atl.bracket_city_game(puzzle.puzzleDate) if use_saved_progress else None
    numbers = [clue_number(puzzle, clue) for clue in solved or []]
    data = views.bracket_city_view(puzzle, include_answers, solved=numbers, saved=saved)
    if use_saved_progress and saved is None:
        data["saved_game"] = None
    return data


@tool()
async def check_bracket_city_answer(clue: int | str, guess: str, date: str | None = None) -> dict[str, Any]:
    """Check a guess for one Bracket City clue (by number or clue text) without revealing the answer
    unless it's right. Case, accents and punctuation are ignored. Default date: the latest puzzle.
    """
    async with client() as atl:
        puzzle = await atl.bracket_city(optional_day(date))
    c = puzzle.clues()[clue_number(puzzle, clue) - 1]
    result: dict[str, Any] = {"date": puzzle.puzzleDate, "number": c.index + 1, "clue": c.text,
                              "correct": same_answer(guess, c.answer)}
    if result["correct"]:
        result["answer"] = c.answer
    return result


@tool()
async def bracket_city_peek(clue: int | str, date: str | None = None, full: bool = False) -> dict[str, Any]:
    """Peek at one Bracket City clue (by number or clue text), like the game's peek: its first letter
    and length, or with full (the game's mega peek) its whole answer. Default date: the latest puzzle.
    """
    async with client() as atl:
        puzzle = await atl.bracket_city(optional_day(date))
    c = puzzle.clues()[clue_number(puzzle, clue) - 1]
    result = {"date": puzzle.puzzleDate, "number": c.index + 1, "clue": c.text, "first_letter": c.answer[:1],
              "length": len(c.answer)}
    if full:
        result["answer"] = c.answer
    return result


# Crosswords


async def get_crossword(atl, series: str, date: str | None, puzzle_id: str | None) -> CrosswordPuzzle:
    if puzzle_id:
        return await atl.crossword(puzzle_id=puzzle_id, series=series)
    return await atl.crossword(date=optional_day(date), series=series)


@tool()
async def crossword(
    series: Series = "daily",
    date: str | None = None,
    puzzle_id: str | None = None,
    include_answers: bool = False,
) -> dict[str, Any]:
    """Get an Atlantic crossword: its grid ("#" is a block) and every entry with its clue, length,
    starting (row, col) and crossing entries. Default: the latest puzzle.

    series is daily (the Atlantic Crossword, from 2018) or inferno (Caleb's Inferno). Use puzzle_id
    (from crossword_archive) instead of date if a date has more than one puzzle. Answers, and the
    letters in the grid, are only included with include_answers.
    """
    async with client() as atl:
        puzzle = await get_crossword(atl, series, date, puzzle_id)
    return views.crossword_view(puzzle, include_answers, clues=False, entries=True)


@tool()
async def check_crossword_answer(
    entry: str,
    guess: str,
    series: Series = "daily",
    date: str | None = None,
    puzzle_id: str | None = None,
    reveal: bool = False,
) -> dict[str, Any]:
    """Check a guess for one crossword entry, such as "17-Across", without revealing the answer
    unless it's right or reveal is true. Only letters and digits are compared. Default: the latest puzzle.
    """
    async with client() as atl:
        puzzle = await get_crossword(atl, series, date, puzzle_id)
    wanted = entry.strip().lower().replace(" ", "-")
    found = next((e for e in puzzle.entries() if e.id.lower() == wanted), None)
    if found is None:
        raise ToolError(f"No entry {entry!r} in crossword {puzzle.id}; use an id such as 1-Across")
    result: dict[str, Any] = {"id": puzzle.id, "entry": found.id, "clue": strip_html(found.clue),
                              "correct": letters(guess) == letters(found.answer)}
    if len(letters(guess)) != len(found.cells) and not result["correct"]:
        result["note"] = f"The answer has {len(found.cells)} squares"
    if result["correct"] or reveal:
        result["answer"] = found.answer
    return result


@tool()
async def crossword_archive(
    series: Series = "daily",
    date_start: str | None = None,
    date_end: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """List a series' crosswords, newest first, with their puzzle IDs, dates, titles, authors and sizes."""
    async with client() as atl:
        listings = await atl.crosswords(series, optional_day(date_start), optional_day(date_end),
                                        limit=max(1, min(limit, 500)))
    return [views.crossword_listing_row(p) for p in listings]


@tool()
async def crossword_progress(
    series: Series = "daily",
    date: str | None = None,
    puzzle_id: str | None = None,
) -> dict[str, Any]:
    """Get the user's saved play of a crossword (default: the latest): whether it's started or
    solved, solve time in seconds, correct entries and whether check, reveal or hints were used.
    Needs cookies.
    """
    async with client() as atl:
        puzzle = await get_crossword(atl, series, date, puzzle_id)
        play = await atl.crossword_play(puzzle.id, series)
    return views.crossword_result(puzzle, play)


# Rabbithole


@tool()
async def rabbithole(
    puzzle_id: str | None = None,
    answered: int = 0,
    use_saved_progress: bool = False,
    include_hints: bool = False,
    include_choices: bool = False,
    include_answers: bool = False,
) -> dict[str, Any]:
    """Get a Rabbithole puzzle (weekdays from 2026-08-12; default the latest): seven trivia questions,
    each answer leading to the next.

    Each question mentions the previous answer, so only the questions the user has answered (answered,
    a count) and the next one are shown, with answers for the answered ones. use_saved_progress takes
    the count from the user's saved game (needs cookies). include_hints adds the game's hints;
    include_choices adds the multiple choice options (the right answer and two wrong ones, sorted).
    Every question and answer is only included with include_answers.
    """
    async with client() as atl:
        puzzle = await atl.rabbithole(puzzle_id)
        saved = await atl.rabbithole_game(puzzle) if use_saved_progress else None
    if saved is not None:
        answered = len(saved.data.questionResults)
    data = views.rabbithole_view(puzzle, include_answers, answered, include_hints, include_choices)
    if use_saved_progress:
        data["saved_game"] = saved and {"progress": saved.progress.value, "score": saved.data.score,
                                        "results": saved.data.questionResults}
    return data


@tool()
async def check_rabbithole_answer(
    question: int,
    guess: str,
    puzzle_id: str | None = None,
    reveal: bool = False,
) -> dict[str, Any]:
    """Check a guess for a Rabbithole question (numbered from 1) with the game's own fuzzy matching,
    without revealing the answer unless it's right or reveal is true. When it's right, the next
    question is included. Default: the latest puzzle.
    """
    async with client() as atl:
        puzzle = await atl.rabbithole(puzzle_id)
    if not 1 <= question <= len(puzzle.questions):
        raise ToolError(f"No question {question}: this puzzle has questions 1 to {len(puzzle.questions)}")
    q = puzzle.questions[question - 1]
    result: dict[str, Any] = {"id": puzzle.id, "question": question, "correct": q.accepts(guess)}
    if result["correct"] or reveal:
        result["answer"] = q.canonicalAnswer
    if result["correct"] and question < len(puzzle.questions):
        result["next_question"] = puzzle.questions[question].question
    return result


@tool()
async def rabbithole_archive(date_start: str | None = None, date_end: str | None = None) -> list[dict[str, Any]]:
    """List the Rabbithole puzzles published between two dates (default: the last 30 days), newest
    first, with their IDs, dates and bylines (no questions or answers).
    """
    first, last = window(date_start, date_end)
    async with client() as atl:
        puzzles = await atl.rabbithole_puzzles(first, last)
    return [views.rabbithole_listing_row(p) for p in puzzles]


# Trivia and Stacks (ended)


@tool()
async def trivia_archive(limit: int = 20) -> list[dict[str, Any]]:
    """List Atlantic Trivia articles, newest first, with their article IDs, dates and titles.

    Trivia ended on 2026-08-14. Daily quizzes with questions start on 2026-03-13; older entries
    are weekly newsletter roundups without questions.
    """
    async with client() as atl:
        articles = await atl.trivia_articles(limit=max(1, min(limit, 400)))
    return [views.trivia_listing_row(a) for a in articles]


@tool()
async def trivia(article: str, include_hints: bool = False, include_answers: bool = False) -> dict[str, Any]:
    """Get a day's Atlantic Trivia questions, from an article ID or URL (see trivia_archive).

    include_hints adds hints. Answers, explanations and related articles are only included with
    include_answers; use check_trivia_answer to check a guess.
    """
    async with client() as atl:
        quiz = await atl.trivia(article)
    if not quiz.questions:
        raise ToolError(f"Article {quiz.article_id} has no trivia questions (daily quizzes start on 2026-03-13)")
    return views.trivia_view(quiz, include_answers, include_hints)


@tool()
async def check_trivia_answer(article: str, question: int, guess: str, reveal: bool = False) -> dict[str, Any]:
    """Check a guess for an Atlantic Trivia question (numbered from 1) with the game's fuzzy matching,
    without revealing the answer unless it's right or reveal is true.
    """
    async with client() as atl:
        quiz = await atl.trivia(article)
    if not 1 <= question <= len(quiz.questions):
        raise ToolError(f"No question {question}: this quiz has {len(quiz.questions)} questions")
    q = quiz.questions[question - 1]
    result: dict[str, Any] = {"id": quiz.article_id, "question": question, "correct": q.accepts(guess)}
    if result["correct"] or reveal:
        result["answer"] = q.canonicalAnswer
    return result


@tool()
async def stacks(date: str, include_answers: bool = False) -> dict[str, Any]:
    """Get a Stacks puzzle (2025-06-17 to 2026-08-24, when the game ended): the words to drop and
    the base row ("-" is an empty column). Drop each word so its letters fall down their columns,
    making every row a word.

    The solution (each word's column, numbered from 1, in order, and the finished board) is only
    included with include_answers.
    """
    async with client() as atl:
        puzzle = await atl.stacks(day(date).isoformat())
    return views.stacks_view(puzzle, include_answers)


@tool()
async def games() -> list[dict[str, Any]]:
    """List the games on The Atlantic's games hub, with descriptions and links."""
    async with client() as atl:
        hub = await atl.games()
    return [views.game_row(g) for g in hub]


# The user's own data


@tool()
async def account() -> dict[str, Any]:
    """Check whether the server has the user's Atlantic login, when it expires, and their
    subscription entitlements. Read from the cookies, without a request.
    """
    async with client() as atl:
        user = atl.account
    if user is None:
        return {"logged_in": False, "help": COOKIE_HELP}
    return {"logged_in": not user.expired, **views.account_view(user)}


@tool()
async def bracket_city_history(date_start: str | None = None, date_end: str | None = None) -> list[dict[str, Any]]:
    """Get the user's Bracket City results for a date range (default: the last 30 days), newest
    first: status, clues solved, wrong guesses, keystrokes, help used and whether it was solved on the
    day. Dates without a saved game are listed as not played. Needs cookies.
    """
    first, last = window(date_start, date_end)
    async with client() as atl:
        dates = [d for d in await atl.bracket_city_dates() if first <= d <= last]
        played = await atl.bracket_city_games(first, last)
    return views.bracket_city_results(dates, played)


@tool()
async def bracket_city_stats(date_start: str | None = None, date_end: str | None = None) -> dict[str, Any]:
    """Get the user's Bracket City stats (default: the whole archive): played, completed, streaks,
    games solved on the day, keystroke efficiency, perfect and clean games, wrong guesses and peeks.
    Computed from saved games; needs cookies.
    """
    first, last = window(date_start, date_end, days=None)
    async with client() as atl:
        played = await atl.bracket_city_games(first, last)
    return {"date_start": first, "date_end": last,
            **views.stats_view(game_stats.bracket_city_stats(played, today=today()))}


@tool()
async def rabbithole_history(date_start: str | None = None, date_end: str | None = None) -> list[dict[str, Any]]:
    """Get the user's Rabbithole results for a date range (default: the last 30 days), newest first:
    status, score (out of 21) and each question's result (correct_first_try, correct_with_hint,
    correct_with_choice or incorrect). Puzzles without a saved game are listed as not played. Needs
    cookies.
    """
    first, last = window(date_start, date_end)
    async with client() as atl:
        puzzles = await atl.rabbithole_puzzles(first, last)
        played = await atl.rabbithole_games(first, last)
    return views.rabbithole_results(puzzles, played)


@tool()
async def rabbithole_stats(date_start: str | None = None, date_end: str | None = None) -> dict[str, Any]:
    """Get the user's Rabbithole stats (default: every puzzle): played, completed, total and average
    score, perfect games and how questions were answered. Computed from saved games; needs cookies.
    """
    first, last = window(date_start, date_end, days=None)
    async with client() as atl:
        played = await atl.rabbithole_games(first, last)
    return {"date_start": first, "date_end": last, **views.stats_view(game_stats.rabbithole_stats(played))}


# Files


@tool(WRITES_FILE)
async def export_crossword(
    path: str,
    series: Series = "daily",
    date: str | None = None,
    puzzle_id: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Save an Atlantic crossword as a file for other crossword apps. The format comes from the
    path's extension: .puz (Across Lite), .ipuz or .xml (Crossword Compiler). Default: the latest
    puzzle.

    Returns the path and notes on anything the format approximates, such as italics in clues.
    Files are for personal use: the puzzles are The Atlantic's, hosted by Amuse Labs.
    """
    target = Path(path).expanduser()
    fmt = target.suffix.lower().lstrip(".")
    if fmt not in formats.FORMATS:
        raise ToolError("Use a path ending in .puz, .ipuz or .xml")
    if target.exists() and not overwrite:
        raise ToolError(f"{target} already exists; set overwrite to replace it")
    async with client() as atl:
        puzzle = await get_crossword(atl, series, date, puzzle_id)
    data = formats.export(puzzle, fmt)
    try:
        write_file(target, data, overwrite)
    except FileExistsError:
        # Checked again here: the file may have been created while the puzzle was fetched.
        raise ToolError(f"{target} already exists; set overwrite to replace it") from None
    return {"path": str(target.resolve()), "format": fmt, "bytes": len(data), "id": puzzle.id,
            "date": puzzle.date, "notes": formats.fidelity(puzzle, fmt)}


def main() -> None:
    """Run the MCP server over stdio."""
    server.run("stdio")


if __name__ == "__main__":
    main()
