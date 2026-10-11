"""Check every Atlantic game against the live services.

Runs nightly in GitHub Actions (.github/workflows/live.yml) so we find out
when The Atlantic or Amuse Labs changes something before users do. Uses no
cookies, unless ATLANTIC_COOKIES is set, which adds a check of your saved
games.

    pip install -e ".[test]"
    python scripts/live_check.py [--json results.json] [--badge badge.json] [--summary summary.md]

Exits 1 if any check fails.
"""
import argparse
import datetime
import json
import os
import sys
import time
import traceback
import zoneinfo
from collections.abc import Callable

import ipuz
import puz

import atlgames
from atlgames import AtlanticGamesClient
from atlgames import AtlanticGamesNotFoundError
from atlgames import amuse
from atlgames import formats

NEW_YORK = zoneinfo.ZoneInfo("America/New_York")


def checks(client: AtlanticGamesClient, today: datetime.date) -> list[tuple[str, Callable[[], str]]]:
    """Return (name, check) pairs. Each check returns a short detail or raises."""
    week_ago = (today - datetime.timedelta(days=6)).isoformat()

    def bracket_city() -> str:
        dates = client.bracket_city_dates()
        assert dates[0] == "2025-01-01", dates[:1]
        puzzle = client.bracket_city(dates[-1])
        steps = puzzle.steps()
        assert len(steps) == len(puzzle.solutions) and "[" not in puzzle.solved_text
        return f"{dates[-1]}, {len(steps)} clues, {len(dates)} in the archive"

    def bracket_city_future() -> str:
        day = (today + datetime.timedelta(days=30)).isoformat()
        try:
            client.bracket_city(day)
        except AtlanticGamesNotFoundError:
            return f"{day} isn't published yet"
        raise AssertionError(f"{day} is already published")

    def crossword(series: str) -> str:
        listings = client.crosswords(series, limit=5)
        assert listings, "no crosswords"
        puzzle = client.crossword(puzzle_id=listings[0].puzzleId, series=series)
        assert puzzle.entries() and puzzle.grid()
        assert client._passes == amuse.SCRAMBLE_PASSES, f"new scramble {client._passes}; update SCRAMBLE_PASSES"
        return f"{puzzle.id} {puzzle.w}x{puzzle.h}, {len(puzzle.entries())} entries"

    def crossword_by_date() -> str:
        listings = client.crosswords(date_start=week_ago, date_end=today.isoformat())
        assert listings, "no crosswords this week"
        puzzle = client.crossword(listings[-1].date)
        assert puzzle.id == listings[-1].puzzleId, (puzzle.id, listings[-1].puzzleId)
        return f"{len(listings)} this week; {listings[-1].date} is {puzzle.id}"

    def unpublished_crossword() -> str:
        day = today + datetime.timedelta(days=30)
        try:
            client.crossword(puzzle_id=f"atlantic_{day:%Y%m%d}")
        except AtlanticGamesNotFoundError:
            return "PuzzleMe error page"
        raise AssertionError(f"atlantic_{day:%Y%m%d} is already published")

    def rabbithole() -> str:
        puzzle = client.rabbithole()
        assert len(puzzle.questions) == 7 and all(q.accepts(q.canonicalAnswer) for q in puzzle.questions)
        assert client.rabbithole(puzzle.id).id == puzzle.id
        return f"#{puzzle.id} from {puzzle.date}"

    def trivia() -> str:
        articles = client.trivia_articles(limit=3)
        assert len(articles) == 3
        # The final daily edition, with structured questions.
        last = client.trivia(688280)
        assert len(last.questions) == 3, len(last.questions)
        return f"latest {articles[0].date}; {len(last.questions)} questions on {last.date}"

    def stacks() -> str:
        puzzles = client.stacks_puzzles()
        assert len(puzzles) == 434, len(puzzles)
        assert all(" " not in row.strip() for p in puzzles for row in p.rows()[1:])
        return f"{len(puzzles)} puzzles, {puzzles[0].date} to {puzzles[-1].date}"

    def games() -> str:
        hub = client.games()
        assert hub and all(g.slug for g in hub)
        return ", ".join(g.slug for g in hub)

    def exports() -> str:
        puzzle = client.crossword(puzzle_id="atlantic_20261010")
        data = formats.to_puz(puzzle)
        assert puz.load(data).tobytes() == data, ".puz checksums"
        ipuz.read(json.dumps(formats.to_ipuz(puzzle)))
        assert formats.to_xml(puzzle).startswith("<?xml")
        return "a daily crossword as .puz, .ipuz and .xml"

    return [
        ("Bracket City", bracket_city),
        ("Bracket City future", bracket_city_future),
        ("Crossword", lambda: crossword("daily")),
        ("Caleb's Inferno", lambda: crossword("inferno")),
        ("Crossword by date", crossword_by_date),
        ("Unpublished crossword", unpublished_crossword),
        ("Rabbithole", rabbithole),
        ("Trivia", trivia),
        ("Stacks", stacks),
        ("Games hub", games),
        ("Crossword export", exports),
    ]


def user_checks(client: AtlanticGamesClient) -> list[tuple[str, Callable[[], str]]]:
    """Checks that need cookies. Details avoid personal data."""
    def account() -> str:
        account = client.account
        assert account and not account.expired, "the atljwt6 cookie has expired"
        return f"expires {account.expires_at:%Y-%m-%d}" if account.expires_at else "no expiry"

    def bracket_city_games() -> str:
        last = datetime.datetime.now(NEW_YORK).date()
        games = client.bracket_city_games((last - datetime.timedelta(days=29)).isoformat(), last.isoformat())
        return f"{len(games)} saved games in the last 30 days"

    def rabbithole_game() -> str:
        game = client.rabbithole_game(client.rabbithole())
        return "latest game saved" if game else "latest game not played"

    def crossword_play() -> str:
        play = client.crossword_play(client.crosswords(limit=1)[0].puzzleId)
        return "today's crossword started" if play.started else "today's crossword not started"

    return [("Account", account), ("Bracket City games", bracket_city_games),
            ("Rabbithole game", rabbithole_game), ("Crossword play", crossword_play)]


def run(name: str, check: Callable[[], str]) -> dict:
    start = time.monotonic()
    try:
        detail, ok = check(), True
    except Exception as err:  # noqa: BLE001 - every failure is reported
        detail, ok = f"{type(err).__name__}: {err}"[:300], False
        traceback.print_exc()
    return {"name": name, "ok": ok, "detail": detail, "seconds": round(time.monotonic() - start, 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", help="Write the results as JSON.")
    parser.add_argument("--badge", help="Write a shields.io endpoint badge as JSON.")
    parser.add_argument("--summary", help="Append a Markdown summary (e.g. $GITHUB_STEP_SUMMARY).")
    args = parser.parse_args()

    now = datetime.datetime.now(NEW_YORK)
    selected = checks(AtlanticGamesClient(), now.date())
    if os.environ.get("ATLANTIC_COOKIES"):
        selected += user_checks(AtlanticGamesClient(cookies=os.environ["ATLANTIC_COOKIES"]))
    results = [run(name, check) for name, check in selected]
    passed = sum(r["ok"] for r in results)

    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['name']:<22} {r['detail']}")
    print(f"\n{passed}/{len(results)} checks passed")

    report = {"checked_at": now.isoformat(timespec="seconds"), "version": atlgames.__version__,
              "passed": passed, "total": len(results), "results": results}
    if args.json:
        with open(args.json, "w") as file:
            json.dump(report, file, indent=2)
    if args.badge:
        badge = {
            "schemaVersion": 1,
            "label": "Atlantic live check",
            "message": f"{passed}/{len(results)} passing · {now:%b} {now.day}",
            "color": "brightgreen" if passed == len(results) else "red",
        }
        with open(args.badge, "w") as file:
            json.dump(badge, file)
    if args.summary:
        with open(args.summary, "a") as file:
            file.write(f"## Atlantic live check: {passed}/{len(results)} passing\n\n"
                       f"{now:%Y-%m-%d %H:%M %Z}, atlantic-games {atlgames.__version__}\n\n"
                       "| | Check | Detail | Seconds |\n|---|---|---|---|\n")
            for r in results:
                detail = r["detail"].replace("|", "\\|")
                file.write(f"| {'✅' if r['ok'] else '❌'} | {r['name']} | {detail} | {r['seconds']} |\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
