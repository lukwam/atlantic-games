"""Answers that repeat across recent Atlantic crosswords, and how each was clued.

Contains spoilers for the crosswords it looks at.

    pip install atlantic-games
    python clue_reuse.py --days 30
"""
import argparse
import collections
import datetime

from atlgames import AtlanticGamesClient
from atlgames.models import strip_html


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30, help="How many days back to look.")
    parser.add_argument("--series", default="daily", choices=["daily", "inferno"])
    parser.add_argument("--min-length", type=int, default=4, help="Ignore shorter answers.")
    args = parser.parse_args()

    end = datetime.date.today()
    start = end - datetime.timedelta(days=args.days - 1)
    clues = collections.defaultdict(list)
    with AtlanticGamesClient() as client:
        for listing in client.crosswords(args.series, start.isoformat(), end.isoformat()):
            puzzle = client.crossword(puzzle_id=listing.puzzleId, series=args.series)
            for entry in puzzle.entries():
                if len(entry.answer) >= args.min_length:
                    clues[entry.answer].append((puzzle.date, strip_html(entry.clue)))

    repeats = sorted(clues.items(), key=lambda item: (-len(item[1]), item[0]))
    for answer, uses in repeats:
        if len(uses) < 2:
            break
        print(f"{answer} ({len(uses)})")
        for date, clue in sorted(uses):
            print(f"    {date}  {clue}")


if __name__ == "__main__":
    main()
