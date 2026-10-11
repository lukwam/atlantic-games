"""Stacks, Patrick Berry's word-dropping game (2025-06-17 to 2026-08-24).

Stacks ended on 2026-08-24. Every puzzle ships inside the game's own
JavaScript, so the whole archive comes from two requests: the game page,
for the current script's name, and the script.

Each puzzle is a few words and a base row. You drop the words onto the
board; each letter falls down its own column onto whatever is there, and
the goal is to make every row a word. A solution step `wordIndex * 10 +
column` drops that word with its first letter in that column.
"""
import datetime
import json
import re
from dataclasses import dataclass

from atlgames.exceptions import AtlanticGamesParseError

STACKS_URL = "https://stacks.games.theatlantic.com/"
FIRST_DATE = datetime.date(2025, 6, 17)
LAST_DATE = datetime.date(2026, 8, 24)

_PAGE_SCRIPT = re.compile(r"/_next/static/chunks/app/page-[0-9a-f]+\.js")
_PUZZLES = re.compile(r"JSON\.parse\('(\[\{\"wordStrings\".*?\])'\)", re.S)


def page_script_url(html: str) -> str:
    """Return the URL of the script with the puzzles, from the game page."""
    match = _PAGE_SCRIPT.search(html)
    if not match:
        raise AtlanticGamesParseError("Couldn't find the Stacks puzzle script in the game page")
    return STACKS_URL.rstrip("/") + match.group(0)


def puzzles_from_script(js: str) -> list[dict]:
    """Return the puzzle list from the Stacks script, in date order."""
    match = _PUZZLES.search(js)
    if not match:
        raise AtlanticGamesParseError("Couldn't find the puzzles in the Stacks script")
    text = match.group(1)
    try:
        # A JS single-quoted string: undo its escapes, then parse the JSON.
        text = text.encode("latin-1", "backslashreplace").decode("unicode_escape")
        return json.loads(text)
    except ValueError:
        raise AtlanticGamesParseError("The Stacks puzzles aren't valid JSON") from None


def puzzle_index(date: str | datetime.date) -> int:
    """Return the position in the puzzle list of a date's puzzle.

    Raises ValueError outside 2025-06-17 to 2026-08-24.
    """
    day = datetime.date.fromisoformat(date) if isinstance(date, str) else date
    if not FIRST_DATE <= day <= LAST_DATE:
        raise ValueError(f"Stacks puzzles run from {FIRST_DATE} to {LAST_DATE}")
    return (day - FIRST_DATE).days


def date_of(index: int) -> str:
    """Return the date of the puzzle at a position in the list."""
    return (FIRST_DATE + datetime.timedelta(days=index)).isoformat()


@dataclass(frozen=True)
class Drop:
    """One move: drop a word with its first letter in a column."""
    word: str
    word_index: int
    column: int


def decode_solution(words: list[str], solution: list[int]) -> list[Drop]:
    """Return a puzzle's solution as drops."""
    return [Drop(words[step // 10], step // 10, step % 10) for step in solution]


def simulate(base: str, drops: list[Drop]) -> list[str]:
    """Return the board's rows, top first, after dropping the words.

    `base` is the bottom row, with `-` for empty columns. Empty squares in
    the result are spaces.
    """
    width = max([len(base)] + [d.column + len(d.word) for d in drops])
    columns: list[list[str]] = [[] for _ in range(width)]
    for col, letter in enumerate(base):
        if letter != "-":
            columns[col].append(letter)
    for drop in drops:
        for offset, letter in enumerate(drop.word):
            columns[drop.column + offset].append(letter)
    height = max((len(c) for c in columns), default=0)
    rows = []
    for level in range(height - 1, -1, -1):
        rows.append("".join(c[level] if level < len(c) else " " for c in columns).rstrip())
    return rows
