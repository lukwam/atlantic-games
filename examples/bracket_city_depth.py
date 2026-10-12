"""The most deeply nested Bracket City puzzles in a date range.

No spoilers: prints each puzzle's depth and clue count, not its answers.

    pip install atlantic-games
    python bracket_city_depth.py --from 2026-09-01 --top 5
"""
import argparse

from atlgames import AtlanticGamesClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="start", default=None, help="First date (default: 30 puzzles ago).")
    parser.add_argument("--to", dest="end", default=None, help="Last date (default: the latest).")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    with AtlanticGamesClient() as client:
        dates = client.bracket_city_dates()
        dates = [d for d in dates if (not args.start or d >= args.start) and (not args.end or d <= args.end)]
        if not args.start:
            dates = dates[-30:]
        # One request per puzzle; keep ranges modest to be polite.
        puzzles = [client.bracket_city(date) for date in dates]

    puzzles.sort(key=lambda p: (-p.depth, -len(p.clues()), p.puzzleDate))
    for puzzle in puzzles[:args.top]:
        print(f"{puzzle.puzzleDate}  depth {puzzle.depth}  {len(puzzle.clues())} clues  by {puzzle.author}")


if __name__ == "__main__":
    main()
