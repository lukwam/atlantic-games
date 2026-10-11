"""Live checks against The Atlantic and Amuse Labs.

Deselected by default; run with `pytest -m live`. Each test makes one or two
requests, to notice when a service changes how it answers.
"""
import pytest

from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesClient
from atlgames import AtlanticGamesNotFoundError
from atlgames import amuse
from tests.support import cookies

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client():
    with AtlanticGamesClient() as client:
        yield client


def test_bracket_city(client):
    puzzle = client.bracket_city("2026-10-08")
    assert puzzle.solved_text == "Raytheon patents the microwave"
    assert len(puzzle.steps()) == len(puzzle.solutions) == 12


def test_bracket_city_index(client):
    dates = client.bracket_city_dates()
    assert dates[0] == "2025-01-01" and len(dates) > 640


def test_bracket_city_future_date(client):
    with pytest.raises(AtlanticGamesNotFoundError):
        client.bracket_city("2099-01-01")


def test_crossword(client):
    puzzle = client.crossword(puzzle_id="atlantic_20261010")
    assert puzzle.grid()[0][2:5] == ["J", "A", "F"]
    assert client._passes == amuse.SCRAMBLE_PASSES, "Amuse Labs changed its scramble; update SCRAMBLE_PASSES"


def test_unpublished_crossword(client):
    with pytest.raises(AtlanticGamesNotFoundError):
        client.crossword(puzzle_id="atlantic_20991231")


def test_crossword_list(client):
    listings = client.crosswords(limit=3)
    assert len(listings) == 3 and all(x.date for x in listings)


def test_crossword_by_date(client):
    assert client.crossword("2026-10-10").id == "atlantic_20261010"


def test_rabbithole(client):
    puzzle = client.rabbithole(53)
    assert puzzle.date == "2026-10-09" and len(puzzle.questions) == 7
    assert puzzle.questions[0].accepts("Mark Zuckerberg")


def test_unknown_game(client):
    with pytest.raises(AtlanticGamesNotFoundError):
        client.game("no-such-game")


def test_trivia_articles(client):
    assert client.trivia_articles(limit=1)[0].article_id.isdigit()


def test_stacks(client):
    puzzle = client.stacks("2025-06-17")
    assert puzzle.rows()[-1] == "ADMONISH"
    assert len(client.stacks_puzzles()) == 434


def test_saved_games_with_a_fake_login():
    """The Atlantic answers a login it doesn't accept with "Bad request"."""
    with AtlanticGamesClient(cookies=cookies()) as client:
        with pytest.raises(AtlanticGamesAuthenticationError):
            client.bracket_city_game("2026-10-08")
