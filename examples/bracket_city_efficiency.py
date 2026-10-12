"""Your Bracket City keystroke efficiency by weekday.

Needs your atljwt6 cookie in the ATLANTIC_COOKIES environment variable, for
example ATLANTIC_COOKIES="atljwt6=...".

    pip install atlantic-games
    ATLANTIC_COOKIES="atljwt6=..." python bracket_city_efficiency.py --days 180
"""
import argparse
import collections
import datetime
import os
import statistics

from atlgames import AtlanticGamesClient

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=180, help="How many days back to look.")
    args = parser.parse_args()

    end = datetime.date.today()
    start = end - datetime.timedelta(days=args.days - 1)
    with AtlanticGamesClient(cookies=os.environ["ATLANTIC_COOKIES"]) as client:
        games = client.bracket_city_games(start.isoformat(), end.isoformat())

    by_weekday = collections.defaultdict(list)
    for game in games:
        if game.efficiency is not None:
            by_weekday[datetime.date.fromisoformat(game.gameDate).weekday()].append(game.efficiency)

    print(f"{'Day':<4} {'Games':>5} {'Median':>7} {'Best':>6}")
    for day, name in enumerate(WEEKDAYS):
        scores = by_weekday.get(day)
        if scores:
            print(f"{name:<4} {len(scores):>5} {statistics.median(scores):>7.0%} {max(scores):>6.0%}")


if __name__ == "__main__":
    main()
