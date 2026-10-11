"""Date parsing for atlg, in New York time, when The Atlantic's puzzles change."""
import datetime
from collections.abc import Iterator

from atlgames.models import EASTERN

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# The first puzzle each game has, for `--from first`.
FIRST_DATES = {
    "bracket-city": datetime.date(2025, 1, 1),
    "crossword": datetime.date(2018, 9, 24),
    "rabbithole": datetime.date(2026, 8, 12),
    "trivia": datetime.date(2026, 3, 13),
    "stacks": datetime.date(2025, 6, 17),
}
# The last puzzle of games that have ended, for "last".
LAST_DATES = {
    "trivia": datetime.date(2026, 8, 14),
    "stacks": datetime.date(2026, 8, 24),
}


def today() -> datetime.date:
    """Return today's date in New York."""
    return datetime.datetime.now(EASTERN).date()


def parse_date(value: str, game: str | None = None) -> datetime.date:
    """Parse a date argument.

    Accepts YYYY-MM-DD, today, yesterday, tomorrow, a weekday name (the most
    recent one, including today), "first" for the game's first puzzle, or
    "last" for the last puzzle of a game that has ended. Raises ValueError
    for anything else.
    """
    text = value.strip().lower()
    now = today()
    if text == "today":
        return now
    if text == "yesterday":
        return now - datetime.timedelta(days=1)
    if text == "tomorrow":
        return now + datetime.timedelta(days=1)
    if text in WEEKDAYS:
        return now - datetime.timedelta(days=(now.weekday() - WEEKDAYS.index(text)) % 7)
    if text == "first":
        if game not in FIRST_DATES:
            raise ValueError('"first" is only available for a specific game')
        return FIRST_DATES[game]
    if text == "last":
        return LAST_DATES.get(game, now)
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ValueError(
            f"Invalid date {value!r}: use YYYY-MM-DD, today, yesterday, tomorrow or a weekday"
        ) from None


def date_range(start: datetime.date, end: datetime.date) -> Iterator[datetime.date]:
    """Yield each date from start to end, inclusive."""
    for offset in range((end - start).days + 1):
        yield start + datetime.timedelta(days=offset)


def format_seconds(seconds: int | float | None) -> str:
    """Format a duration as M:SS or H:MM:SS."""
    if seconds is None:
        return ""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"
