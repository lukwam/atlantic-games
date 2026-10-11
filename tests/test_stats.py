"""Stats computed from saved games."""
import datetime

import pytest

from atlgames.models import BracketCityGame
from atlgames.models import RabbitholeGame
from atlgames.stats import _streaks
from atlgames.stats import bracket_city_stats
from atlgames.stats import rabbithole_stats
from tests.support import load

TODAY = datetime.date(2026, 10, 11)


def game(date: str, progress: str = "complete", **state) -> BracketCityGame:
    data = {"solvedExpressions": ["a"], "totalKeystrokes": 10, "minimumKeystrokes": 10, **state}
    return BracketCityGame(gameKey=f"{date}:bracket-city:v1", gameSlug="bracket-city", gameDate=date, gameId="v1",
                           progress=progress, gameState=data)


@pytest.mark.parametrize("dates,today,expected", [
    ([], TODAY, (0, 0)),
    (["2026-10-11"], TODAY, (1, 1)),
    (["2026-10-09", "2026-10-10"], TODAY, (2, 2)),          # reaching yesterday still counts
    (["2026-10-08", "2026-10-09"], TODAY, (0, 2)),          # broken two days ago
    (["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-10", "2026-10-11"], TODAY, (2, 3)),
    (["2026-10-11", "2026-10-10", "2026-10-10"], TODAY, (2, 2)),  # order and duplicates don't matter
    (["2026-02-28", "2026-03-01"], datetime.date(2026, 3, 1), (2, 2)),
])
def test_streaks(dates, today, expected):
    assert _streaks(dates, today) == expected


def test_bracket_city_stats():
    games = [
        game("2026-10-08", solvedOnPubDate=True, wrongGuesses=2, totalKeystrokes=20),
        game("2026-10-09", solvedOnPubDate=True, peekedClues=["x"]),
        game("2026-10-10", solvedOnPubDate=False, megaPeekedClues=["y"], hintModeClues=["z"]),
        game("2026-10-11", "inProgress"),
        game("2026-10-01", "notStarted", solvedExpressions=[]),  # opened, never played: skipped
        game("2026-09-30", "notStarted"),                         # reset after playing: counts as played
        game("2026-09-01", solvedOnPubDate=None),
    ]
    stats = bracket_city_stats(games, today=TODAY)
    assert (stats.played, stats.completed, stats.in_progress) == (6, 4, 2)
    assert stats.completed_dates == ["2026-09-01", "2026-10-08", "2026-10-09", "2026-10-10"]
    assert (stats.current_streak, stats.longest_streak) == (3, 3)
    assert (stats.solved_on_the_day, stats.on_the_day_longest_streak) == (2, 2)
    assert stats.efficiency == 40 / 50
    assert stats.perfect == 3 and stats.clean == 1
    assert (stats.wrong_guesses, stats.peeks, stats.mega_peeks, stats.hints) == (2, 1, 1, 1)


def test_bracket_city_stats_current_streak_needs_today_or_yesterday():
    games = [game("2026-10-07"), game("2026-10-08")]
    assert bracket_city_stats(games, today=datetime.date(2026, 10, 9)).current_streak == 2
    assert bracket_city_stats(games, today=datetime.date(2026, 10, 10)).current_streak == 0


def test_bracket_city_stats_empty():
    stats = bracket_city_stats([])
    assert stats.played == 0 and stats.efficiency is None and stats.current_streak == 0


def test_bracket_city_stats_from_saved_games():
    items = load("graphql/batch_game_states.json")["data"]["batchGameStates"]["items"]
    games = [BracketCityGame(**i) for i in items if i["gameSlug"] == "bracket-city"]
    stats = bracket_city_stats(games, today=TODAY)
    assert (stats.played, stats.completed, stats.in_progress) == (3, 2, 1)
    assert stats.current_streak == 0 and stats.longest_streak == 1
    assert stats.solved_on_the_day == 1


def rabbithole_game(progress: str, results: list[str], score: int) -> RabbitholeGame:
    return RabbitholeGame(gameKey="k", gameSlug="rabbithole", gameDate="2026-10-09", gameId="53", progress=progress,
                          gameState={"questionResults": results, "score": score})


def test_rabbithole_stats():
    games = [
        rabbithole_game("complete", ["correct_first_try"] * 7, 21),
        rabbithole_game("complete", ["correct_first_try"] * 5 + ["correct_with_hint", "incorrect"], 17),
        rabbithole_game("inProgress", ["correct_with_choice"], 1),
        rabbithole_game("notStarted", [], 0),
    ]
    stats = rabbithole_stats(games)
    assert (stats.played, stats.completed, stats.total_score, stats.perfect) == (3, 2, 38, 1)
    assert stats.average_score == 19
    assert stats.results == {"correct_first_try": 12, "correct_with_hint": 1, "incorrect": 1,
                             "correct_with_choice": 1}
    assert rabbithole_stats([]).average_score is None
