"""Stacks: reading puzzles from the game's script and replaying solutions."""
import datetime

import pytest

from atlgames import AtlanticGamesParseError
from atlgames import stacks
from atlgames.models import StacksPuzzle
from tests.support import text

SCRIPT = text("stacks/page-f3bdd79621bb6f9e.js")
PUZZLES = stacks.puzzles_from_script(SCRIPT)


def test_page_script_url():
    assert stacks.page_script_url(text("stacks/page.html")) == (
        "https://stacks.games.theatlantic.com/_next/static/chunks/app/page-f3bdd79621bb6f9e.js")


def test_page_script_url_missing():
    with pytest.raises(AtlanticGamesParseError, match="puzzle script"):
        stacks.page_script_url("<html><script src='/_next/static/chunks/main.js'></script></html>")


def test_puzzles_from_script():
    assert len(PUZZLES) == 40
    first = PUZZLES[0]
    assert first == {"wordStrings": ["ATTAIN", "DRONES", "GIVETH", "WORLDS"], "blackPos": "--M--I",
                     "solution": [11, 22, 32, 0], "id": 1, "title": ""}
    # The list is in date order, not ID order.
    assert [p["id"] for p in PUZZLES[:3]] == [1, 0, 2]


def test_puzzles_from_script_unescapes_js():
    js = "let U=JSON.parse('[{\"wordStrings\":[\"DON\\'T\",\"CAF\\u00c9\"],\"title\":\"\\\\\"Hi\\\\\" \\u2014 é\"}]');"
    assert stacks.puzzles_from_script(js) == [{"wordStrings": ["DON'T", "CAFÉ"], "title": "\"Hi\" — é"}]


@pytest.mark.parametrize("js,message", [
    ("let U=[]", "find the puzzles"),
    ("JSON.parse('[{\"wordStrings\":[}]')", "aren't valid JSON"),
])
def test_puzzles_from_script_errors(js, message):
    with pytest.raises(AtlanticGamesParseError, match=message):
        stacks.puzzles_from_script(js)


@pytest.mark.parametrize("date,index", [
    ("2025-06-17", 0),
    (datetime.date(2025, 6, 18), 1),
    ("2026-08-24", 433),
])
def test_dates_and_indexes(date, index):
    assert stacks.puzzle_index(date) == index
    assert stacks.date_of(index) == str(date)


@pytest.mark.parametrize("date", ["2025-06-16", "2026-08-25"])
def test_dates_outside_the_archive(date):
    with pytest.raises(ValueError, match="2025-06-17 to 2026-08-24"):
        stacks.puzzle_index(date)


def test_decode_solution():
    drops = stacks.decode_solution(["ATTAIN", "DRONES", "GIVETH", "WORLDS"], [11, 22, 32, 0])
    assert drops[0] == stacks.Drop("DRONES", 1, 1)
    assert [(d.word_index, d.column) for d in drops] == [(1, 1), (2, 2), (3, 2), (0, 0)]


def test_simulate_first_puzzle():
    puzzle = StacksPuzzle(**PUZZLES[0], date=stacks.date_of(0))
    assert puzzle.rows() == ["  T  N", "  WAIL", "  GORED", " TRIVETS", "ADMONISH"]


def test_simulate_letters_fall_onto_each_column():
    assert stacks.simulate("-A-", [stacks.Drop("BCD", 0, 0), stacks.Drop("EF", 0, 1)]) == [" E", " CF", "BAD"]
    assert stacks.simulate("", []) == []


@pytest.mark.parametrize("index", range(len(PUZZLES)))
def test_solutions_make_words(index):
    """Replaying each solution leaves a word on every row but the top one,
    using every letter of every word once."""
    puzzle = StacksPuzzle(**PUZZLES[index], date=stacks.date_of(index))
    rows = puzzle.rows()
    for row in rows[1:]:
        word = row.strip()
        assert word.isalpha() and word.isupper(), rows
    assert sorted(d.word_index for d in puzzle.drops()) == list(range(len(puzzle.wordStrings)))
    letters = sorted("".join(rows).replace(" ", ""))
    assert letters == sorted("".join(puzzle.wordStrings) + puzzle.blackPos.replace("-", ""))
    for col, letter in enumerate(puzzle.blackPos):
        if letter != "-":
            assert rows[-1][col] == letter
