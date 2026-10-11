"""Stats from your saved games.

The Atlantic has no stats endpoint (unlike NYT's player stats), so these are
computed from saved games. Saved games are snapshots that can go backward
(see `GameState`), so stats describe the games as fetched.

Streaks count consecutive puzzle dates you completed, whenever you played
them. `on_the_day_*` streaks only count games marked as solved on their
publication date, which Bracket City has recorded since about August 2025.
"""
import datetime
from dataclasses import dataclass
from dataclasses import field
from typing import Iterable

from atlgames.models import EASTERN
from atlgames.models import BracketCityGame
from atlgames.models import RabbitholeGame


def _streaks(dates: Iterable[str], today: datetime.date) -> tuple[int, int]:
    """Return (current, longest) runs of consecutive dates. The current run
    must reach today or yesterday."""
    days = sorted({datetime.date.fromisoformat(d) for d in dates})
    longest = run = 0
    previous = None
    for day in days:
        run = run + 1 if previous and (day - previous).days == 1 else 1
        longest = max(longest, run)
        previous = day
    current = run if previous and (today - previous).days <= 1 else 0
    return current, longest


@dataclass
class BracketCityStats:
    """Your Bracket City record."""
    played: int = 0
    completed: int = 0
    in_progress: int = 0
    current_streak: int = 0
    longest_streak: int = 0
    solved_on_the_day: int = 0
    on_the_day_longest_streak: int = 0
    #: Minimum keystrokes over keystrokes typed, across completed games.
    efficiency: float | None = None
    #: Completed with exactly the minimum keystrokes.
    perfect: int = 0
    #: Completed without wrong guesses, peeks or hints.
    clean: int = 0
    wrong_guesses: int = 0
    peeks: int = 0
    mega_peeks: int = 0
    hints: int = 0
    completed_dates: list[str] = field(default_factory=list)


def bracket_city_stats(games: Iterable[BracketCityGame],
                       today: datetime.date | None = None) -> BracketCityStats:
    """Return stats for saved Bracket City games (from `bracket_city_games()`)."""
    today = today or datetime.datetime.now(EASTERN).date()
    stats = BracketCityStats()
    typed = minimum = 0
    on_the_day = []
    for game in games:
        data = game.data
        if game.progress.value == "notStarted" and not data.solvedExpressions:
            continue
        stats.played += 1
        if not game.complete:
            stats.in_progress += 1
            continue
        stats.completed += 1
        stats.completed_dates.append(game.gameDate)
        typed += data.totalKeystrokes
        minimum += data.minimumKeystrokes
        stats.perfect += bool(data.totalKeystrokes) and data.totalKeystrokes == data.minimumKeystrokes
        hints = len(data.peekedClues) + len(data.megaPeekedClues) + len(data.hintModeClues)
        stats.clean += data.wrongGuesses == 0 and hints == 0
        stats.wrong_guesses += data.wrongGuesses
        stats.peeks += len(data.peekedClues)
        stats.mega_peeks += len(data.megaPeekedClues)
        stats.hints += len(data.hintModeClues)
        if data.solvedOnPubDate:
            stats.solved_on_the_day += 1
            on_the_day.append(game.gameDate)
    stats.completed_dates.sort()
    stats.efficiency = minimum / typed if typed else None
    stats.current_streak, stats.longest_streak = _streaks(stats.completed_dates, today)
    stats.on_the_day_longest_streak = _streaks(on_the_day, today)[1]
    return stats


@dataclass
class RabbitholeStats:
    """Your Rabbithole record."""
    played: int = 0
    completed: int = 0
    total_score: int = 0
    average_score: float | None = None
    #: Completed games with every question right on the first try.
    perfect: int = 0
    results: dict[str, int] = field(default_factory=dict)


def rabbithole_stats(games: Iterable[RabbitholeGame]) -> RabbitholeStats:
    """Return stats for saved Rabbithole games (from `rabbithole_games()`)."""
    stats = RabbitholeStats()
    for game in games:
        data = game.data
        if game.progress.value == "notStarted" and not data.questionResults:
            continue
        stats.played += 1
        for result in data.questionResults:
            stats.results[result] = stats.results.get(result, 0) + 1
        if game.complete:
            stats.completed += 1
            stats.total_score += data.score
            stats.perfect += bool(data.questionResults) and all(
                r == "correct_first_try" for r in data.questionResults)
    if stats.completed:
        stats.average_score = stats.total_score / stats.completed
    return stats
