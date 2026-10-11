"""Model tests: dates in New York, answers, saved games."""
import datetime

import pytest

from atlgames import CrosswordSeries
from atlgames import amuse
from atlgames.models import STATE_MODELS
from atlgames.models import BracketCityGame
from atlgames.models import BracketCityPuzzle
from atlgames.models import CrosswordListing
from atlgames.models import CrosswordPlay
from atlgames.models import CrosswordPuzzle
from atlgames.models import GameProgress
from atlgames.models import GameState
from atlgames.models import RabbitholeGame
from atlgames.models import RabbitholePuzzle
from atlgames.models import TriviaArticle
from atlgames.models import TriviaQuestion
from atlgames.models import answer_ratio
from atlgames.models import normalize_answer
from atlgames.models import strip_html
from tests.support import bracket_city_puzzle
from tests.support import crossword_params
from tests.support import load

UTC = datetime.timezone.utc


def ms(*args) -> int:
    return int(datetime.datetime(*args, tzinfo=UTC).timestamp() * 1000)


@pytest.mark.parametrize("when,date", [
    (ms(2026, 10, 11, 4, 1), "2026-10-11"),   # just after midnight in New York (EDT)
    (ms(2026, 10, 11, 3, 59), "2026-10-10"),  # still the evening before
    (ms(2026, 1, 15, 4, 30), "2026-01-14"),   # EST is UTC-5
    (ms(2026, 1, 15, 5, 0), "2026-01-15"),
])
def test_crossword_listing_date_is_in_new_york(when, date):
    assert CrosswordListing(puzzleId="x", publicationTime=when).date == date


def test_crossword_listing_from_graphql():
    listing = CrosswordListing(puzzleId="atlantic_20261010", publicationDateTime="2026-10-10T04:01:00Z")
    assert listing.date == "2026-10-10"
    assert listing.published == datetime.datetime(2026, 10, 10, 4, 1, tzinfo=UTC)
    assert CrosswordListing(puzzleId="x").date is None


def test_crossword_listings_from_amuse():
    items = load("crossword/list.json")["seriesToPuzzleMetadata"]["atlantic"]
    listings = [CrosswordListing(**item) for item in items]
    assert [(x.puzzleId, x.date) for x in listings[:2]] == [
        ("atlantic_20261011", "2026-10-11"), ("atlantic_20261010", "2026-10-10")]
    assert listings[-1].puzzleId == "atlantics_20260614" and listings[-1].date == "2026-06-14"
    assert listings[0].model_dump()["thumbnailURL"].startswith("https://")  # extra fields are kept


def test_crossword_puzzle():
    data = amuse.decode_rawc(crossword_params("atlantic_20261010")["rawc"])
    puzzle = CrosswordPuzzle(**data, series="atlantic")
    assert puzzle.date == "2026-10-10"
    assert puzzle.constructor == "Amanda Rafkin" and puzzle.editor == "Kelsey Dixon"
    assert puzzle.is_block(0, 0) and not puzzle.is_block(0, 2)
    assert puzzle.model_dump()["boxToPlacedWordsIdxs"]
    old = CrosswordPuzzle(**amuse.decode_rawc(crossword_params("2fbb3c8f")["rawc"]))
    assert old.date == "2018-09-24" and old.editor is None and old.constructor == "Caleb Madison"
    assert CrosswordPuzzle(id="x", w=0, h=0, box=[], placedWords=[]).date is None


@pytest.mark.parametrize("value,series", [
    ("daily", CrosswordSeries.daily),
    ("atlantic", CrosswordSeries.daily),
    ("inferno", CrosswordSeries.inferno),
    ("atlantic-inferno", CrosswordSeries.inferno),
    (CrosswordSeries.inferno, CrosswordSeries.inferno),
])
def test_crossword_series(value, series):
    assert CrosswordSeries.coerce(value) is series


def test_crossword_series_unknown():
    with pytest.raises(ValueError):
        CrosswordSeries.coerce("weekly")


def test_crossword_play():
    play = CrosswordPlay(id="atlantic_20261010", playState=0)
    assert play.puzzleId == "atlantic_20261010" and not play.started and play.updated is None
    play = CrosswordPlay(id="x", playState=2, timeTaken=300, updatedTimestamp=ms(2026, 10, 10, 15))
    assert play.started and play.updated == datetime.datetime(2026, 10, 10, 15, tzinfo=UTC)
    assert CrosswordPlay(puzzleId="y", timestamp=ms(2026, 1, 1)).updated.year == 2026


def rabbithole() -> RabbitholePuzzle:
    return RabbitholePuzzle(**load("graphql/rabbithole_latest.json")["data"]["rabbitholePuzzles"]["results"][0])


def test_rabbithole_puzzle():
    puzzle = rabbithole()
    assert puzzle.id == "53"
    assert puzzle.date == "2026-10-09"  # published at midnight in New York
    assert len(puzzle.questions) == 7 and puzzle.max_score == 21
    first = puzzle.questions[0]
    assert first.question.startswith("The director Aaron Sorkin") and "<" not in first.question
    assert first.hint == "Jeremy Strong got cast in The Social Reckoning."
    assert len(first.choices) == 2


@pytest.mark.parametrize("guess,accepted", [
    ("Mark Zuckerberg", True),
    ("mark zuckerberg!", True),
    ("Zuckerburg", True),  # close enough
    ("Zuck", True),        # a valid answer
    ("Lex Luthor", False),
    ("", False),
])
def test_rabbithole_accepts(guess, accepted):
    assert rabbithole().questions[0].accepts(guess) is accepted


@pytest.mark.parametrize("text,normalized", [
    ("  Brené   Brown ", "brene brown"),
    ("Rock 'n' Roll!", "rock n roll"),
    ("Ça-va", "cava"),
])
def test_normalize_answer(text, normalized):
    assert normalize_answer(text) == normalized


def test_answer_ratio():
    assert answer_ratio("Paris", "paris") == 100
    assert answer_ratio("", "") == 100
    assert answer_ratio("", "x") == 0
    assert 0 < answer_ratio("Pariss", "Paris") < 100


def test_strip_html():
    assert strip_html("<div>A &amp; <em>B</em>\n  C</div>") == "A & B C"
    assert strip_html(None) is None


def test_trivia():
    article = TriviaArticle(id="BlogArticle:688280", datePublished="2026-08-14T10:00:00Z", questions=[
        {"id": "1", "questionText": "<p>Capital of <b>France</b>?</p>", "canonicalAnswer": "Paris",
         "validAnswers": ["Paree"]}])
    assert article.article_id == "688280" and article.date == "2026-08-14"
    question = article.questions[0]
    assert isinstance(question, TriviaQuestion)
    assert question.question == "Capital of France?"
    assert question.accepts("paree") and question.accepts("Paris") and not question.accepts("Lyon")


def bracket_city_state(**changes) -> dict:
    item = {"gameKey": "2026-10-08:bracket-city:v1", "gameSlug": "bracket-city", "gameDate": "2026-10-08",
            "gameId": "v1", "progress": "complete", "updatedAt": ms(2026, 10, 8, 14),
            "createdAt": "2026-10-11T12:00:00Z", "userUUID": "00000000-0000-4000-8000-000000000001",
            "gameState": {"solvedExpressions": ["a", "b", "c"], "totalKeystrokes": 80, "minimumKeystrokes": 60,
                          "solvedOnPubDate": True, "isComplete": True}}
    item.update(changes)
    return item


def test_bracket_city_game():
    puzzle = BracketCityPuzzle(**bracket_city_puzzle("2026-10-08"))
    game = BracketCityGame(**bracket_city_state())
    assert game.complete and game.progress is GameProgress.complete
    assert game.efficiency == 0.75
    assert game.solved_fraction(puzzle) == 3 / 12
    assert game.updated == datetime.datetime(2026, 10, 8, 14, tzinfo=UTC)
    assert game.createdAt == datetime.datetime(2026, 10, 11, 12, tzinfo=UTC)
    assert game.data.solvedOnPubDate is True and game.data.wrongGuesses == 0


def test_bracket_city_game_edge_cases():
    puzzle = BracketCityPuzzle(**bracket_city_puzzle("2026-10-08"))
    unfinished = BracketCityGame(**bracket_city_state(progress="inProgress"))
    assert not unfinished.complete and unfinished.efficiency is None
    no_keys = BracketCityGame(**bracket_city_state(gameState={"totalKeystrokes": 0}))
    assert no_keys.efficiency is None and no_keys.data.solvedOnPubDate is None
    many = BracketCityGame(**bracket_city_state(gameState={"solvedExpressions": ["x"] * 20}))
    assert many.solved_fraction(puzzle) == 1.0
    empty = BracketCityPuzzle(puzzleDate="2025-01-01", initialPuzzle="", puzzleSolution="", solutions={})
    assert many.solved_fraction(empty) == 0.0
    assert BracketCityGame(**bracket_city_state(gameState=None)).data.solvedExpressions == []


def test_game_state():
    state = GameState(gameKey="k", gameSlug="new-game", gameDate="2026-10-10", gameId="1", progress="notStarted",
                      newField=1)
    assert not state.complete and state.updated is None
    assert state.model_dump()["newField"] == 1
    with pytest.raises(ValueError):
        GameState(gameKey="k", gameSlug="x", gameDate="d", gameId="1", progress="halfway")
    assert STATE_MODELS["bracket-city"] is BracketCityGame and STATE_MODELS["rabbithole"] is RabbitholeGame


def test_rabbithole_game():
    game = RabbitholeGame(gameKey="2026-10-09:rabbithole:53", gameSlug="rabbithole", gameDate="2026-10-09",
                          gameId="53", progress="complete",
                          gameState={"questionResults": ["correct_first_try"] * 7, "score": 21})
    assert game.data.score == 21 and game.data.questionResults[0] == "correct_first_try"


def _snapshot(model, progress, updated, **state):
    slug = "bracket-city" if model is BracketCityGame else "rabbithole"
    game_id = "v1" if model is BracketCityGame else "53"
    return model(gameKey=f"2026-10-09:{slug}:{game_id}", gameSlug=slug, gameDate="2026-10-09", gameId=game_id,
                 progress=progress, updatedAt=updated, gameState=state)


def test_saved_game_advancement_keeps_the_best_snapshot():
    done = _snapshot(BracketCityGame, "complete", 100, solvedExpressions=["a", "b"])
    reset = _snapshot(BracketCityGame, "notStarted", 300)  # newer, but emptied
    partial = _snapshot(BracketCityGame, "inProgress", 200, solvedExpressions=["a"])
    more = _snapshot(BracketCityGame, "inProgress", 150, solvedExpressions=["a", "b"])
    replayed = _snapshot(BracketCityGame, "complete", 400, solvedExpressions=["a", "b"])

    assert done.better_than(reset) and not reset.better_than(done)
    assert more.better_than(partial)  # more solved beats later
    assert replayed.better_than(done)  # same progress and amount: later wins
    assert not done.better_than(done)
    assert max([reset, partial, done, more], key=lambda s: s.advancement) is done


def test_rabbithole_advancement_counts_answered_questions():
    two = _snapshot(RabbitholeGame, "inProgress", 1, questionResults=["correct_first_try", "incorrect"])
    one = _snapshot(RabbitholeGame, "inProgress", 2, questionResults=["correct_first_try"])
    assert two.solved == 2 and two.better_than(one)


def test_better_than_refuses_different_games():
    a = _snapshot(BracketCityGame, "complete", 1)
    b = a.model_copy(update={"gameDate": "2026-10-10", "gameKey": "2026-10-10:bracket-city:v1"})
    with pytest.raises(ValueError, match="different games"):
        a.better_than(b)
    generic = GameState(gameKey="k", gameSlug="other", gameDate="d", gameId="1", progress="complete")
    assert generic.solved == 0
