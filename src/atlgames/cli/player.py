"""atlg commands about the user: stats, today and history. These need cookies.

The Atlantic has no stats endpoint, so stats are computed from your saved
games (see atlgames.stats). Crossword progress comes from Amuse Labs.
"""
import datetime
import enum
from collections.abc import Iterable
from typing import Annotated
from typing import Optional

import typer
from rich.progress import Progress
from rich.table import Table
from rich.text import Text

from atlgames import AtlanticGamesNotFoundError
from atlgames import views
from atlgames.cli import dates
from atlgames.cli.dates import format_seconds
from atlgames.cli.output import FormatOption
from atlgames.cli.output import emit
from atlgames.cli.output import err_console
from atlgames.cli.output import key_value_table
from atlgames.cli.puzzles import Series
from atlgames.cli.puzzles import SeriesOption
from atlgames.cli.state import date_arg
from atlgames.cli.state import state
from atlgames.stats import bracket_city_stats
from atlgames.stats import rabbithole_stats

FromOption = Annotated[
    Optional[str], typer.Option("--from", help='First date, or "first" (default: 30 days ago).')
]
ToOption = Annotated[Optional[str], typer.Option("--to", help="Last date (default: today).")]

STATUS_STYLES = {"complete": "green", "solved": "green", "in progress": "yellow", "started": "yellow",
                 "not played": "dim"}
# Rabbithole question results, as the game's share text shows them.
RESULT_ICONS = {"correct_first_try": "🟢", "correct_with_hint": "🟡", "correct_with_choice": "🟠",
                "incorrect": "🔴"}


def register(app: typer.Typer) -> None:
    """Add the player commands to the root app."""
    app.command("stats")(stats)
    app.command("today")(today)
    history = typer.Typer(help="Your results for a range of dates.", no_args_is_help=True)
    history.command("bracket-city")(history_bracket_city)
    history.command("rabbithole")(history_rabbithole)
    history.command("crossword")(history_crossword)
    app.add_typer(history, name="history")


def status_text(status: str) -> Text:
    return Text(status, style=STATUS_STYLES.get(status, ""))


def percent(value: float | None) -> str:
    return "" if value is None else f"{100 * value:.1f}%"


class Game(str, enum.Enum):
    all = "all"
    bracket_city = "bracket-city"
    rabbithole = "rabbithole"


def stats(
    game: Annotated[Game, typer.Argument(help="A game for more detail, or all for a summary.")] = Game.all,
    start: Annotated[Optional[str], typer.Option("--from", help="First date (default: the first puzzle).")] = None,
    end: Annotated[Optional[str], typer.Option("--to", help="Last date (default: today).")] = None,
    fmt: FormatOption = None,
) -> None:
    """Show your stats, computed from your saved games.

    Streaks count consecutive puzzle dates you completed, whenever you
    played them. Bracket City's whole archive takes about 30 requests.
    """
    first = date_arg(start).isoformat() if start else None
    last = date_arg(end).isoformat() if end else None
    client = state.client()
    today_ = dates.today()
    bracket = rabbit = None
    if game in (Game.all, Game.bracket_city):
        bracket = bracket_city_stats(client.bracket_city_games(first, last), today_)
    if game in (Game.all, Game.rabbithole):
        rabbit = rabbithole_stats(client.rabbithole_games(first, last))

    if game == Game.all:
        data = [
            {"game": "Bracket City", "played": bracket.played, "completed": bracket.completed,
             "current_streak": bracket.current_streak, "longest_streak": bracket.longest_streak,
             "average_score": None},
            {"game": "Rabbithole", "played": rabbit.played, "completed": rabbit.completed,
             "current_streak": None, "longest_streak": None,
             "average_score": round(rabbit.average_score, 1) if rabbit.average_score is not None else None},
        ]

        def table(data):
            t = Table(title="Atlantic Games stats", title_justify="left", header_style="bold")
            for column in ("Game", "Played", "Completed", "Streak", "Longest streak", "Average score"):
                t.add_column(column, justify="left" if column == "Game" else "right")
            for row in data:
                t.add_row(row["game"], *("" if row[k] is None else str(row[k]) for k in
                                         ("played", "completed", "current_streak", "longest_streak",
                                          "average_score")))
            yield t

        return emit(data, fmt, table)

    if game == Game.bracket_city:
        data = views.stats_view(bracket)

        def table(data):
            yield key_value_table({
                "Played": data["played"], "Completed": data["completed"], "In progress": data["in_progress"],
                "Current streak": data["current_streak"], "Longest streak": data["longest_streak"],
                "Solved on the day": data["solved_on_the_day"],
                "Longest on-the-day streak": data["on_the_day_longest_streak"],
                "Keystroke efficiency": percent(data["efficiency"]),
                "Perfect (minimum keystrokes)": data["perfect"],
                "Clean (no wrong guesses or help)": data["clean"],
                "Wrong guesses": data["wrong_guesses"], "Peeks": data["peeks"],
                "Mega peeks": data["mega_peeks"], "Hints": data["hints"],
            }, title="[bold]Bracket City[/bold]")

        return emit(data, fmt, table)

    data = views.stats_view(rabbit)

    def rabbithole_table(data):
        yield key_value_table({
            "Played": data["played"], "Completed": data["completed"], "Total score": data["total_score"],
            "Average score": "" if data["average_score"] is None else f"{data['average_score']:.1f} of 21",
            "Perfect": data["perfect"],
        }, title="[bold]Rabbithole[/bold]")
        results = data["results"]
        if results:
            t = Table(title="Questions", title_justify="left", show_header=False, box=None)
            t.add_column()
            t.add_column(justify="right")
            for key, icon in RESULT_ICONS.items():
                t.add_row(f"{icon} {key.replace('_', ' ')}", str(results.get(key, 0)))
            yield t

    emit(data, fmt, rabbithole_table)


def today(fmt: FormatOption = None) -> None:
    """Show which of today's games you've played."""
    day = dates.today().isoformat()
    client = state.client()
    keys = [("bracket-city", day, "v1")]
    rabbit = client.rabbithole_puzzles(day, day)
    if rabbit:
        keys.append(("rabbithole", day, rabbit[0].id))
    saved = {(s.gameSlug, s.gameId): s for s in client.game_states(keys)}
    bracket = views.bracket_city_result(day, saved.get(("bracket-city", "v1")))
    rows = [{"game": "Bracket City", "status": bracket["status"],
             "detail": f"{bracket['solved_clues']} clues solved" if bracket["status"] != "not played" else ""}]
    if rabbit:
        result = views.rabbithole_result(rabbit[0], saved.get(("rabbithole", rabbit[0].id)))
        rows.append({"game": "Rabbithole", "status": result["status"],
                     "detail": "".join(RESULT_ICONS.get(r, "") for r in result["results"])
                     + (f" {result['score']}/{result['max_score']}" if result["score"] is not None else "")})
    else:
        rows.append({"game": "Rabbithole", "status": "no puzzle", "detail": "published on weekdays"})
    listings = client.crosswords("daily", day, day, limit=1)
    if listings:
        play = client.crossword_play(listings[0].puzzleId, "daily")
        result = views.crossword_result(listings[0], play)
        rows.append({"game": "Crossword", "status": result["status"],
                     "detail": format_seconds(result["seconds"]) if result["seconds"] else ""})

    def table(data):
        t = Table(title=f"Today's games ({day})", title_justify="left", header_style="bold")
        t.add_column("")
        t.add_column("Game")
        t.add_column("Status")
        t.add_column("Detail")
        for row in data:
            status = row["status"]
            icon = ("[green]✔[/green]" if status in ("complete", "solved")
                    else "[yellow]…[/yellow]" if status in ("in progress", "started") else "[dim]·[/dim]")
            t.add_row(icon, row["game"], status_text(status), row["detail"])
        yield t

    emit(rows, fmt, table)


def date_window(start: str | None, end: str | None, game: str) -> tuple[datetime.date, datetime.date]:
    last = date_arg(end, game) if end else dates.today()
    first = date_arg(start, game) if start else last - datetime.timedelta(days=29)
    if first > last:
        raise typer.BadParameter("--from is after --to")
    return first, last


def progress(items: Iterable, total: int, description: str):
    """Show a progress bar on stderr for long runs."""
    if total <= 7:
        yield from items
        return
    with Progress(console=err_console, transient=True) as bar_:
        task = bar_.add_task(description, total=total)
        for item in items:
            yield item
            bar_.advance(task)


def history_bracket_city(start: FromOption = None, end: ToOption = None, fmt: FormatOption = None) -> None:
    """Your Bracket City results: clues solved, wrong guesses, keystrokes and help used."""
    first, last = date_window(start, end, "bracket-city")
    client = state.client()
    days = [d for d in client.bracket_city_dates() if first.isoformat() <= d <= last.isoformat()]
    rows = views.bracket_city_results(days, client.game_states([("bracket-city", d, "v1") for d in days]))

    def table(data):
        t = Table(title=f"Bracket City {first} to {last}", title_justify="left", header_style="bold")
        for column in ("Date", "Status", "Clues", "Wrong", "Keys", "Eff.", "Help", "On day"):
            t.add_column(column, justify="left" if column in ("Date", "Status") else "right", no_wrap=True)
        for row in data:
            played = row["status"] != "not played"
            help_used = (row["peeks"] or 0) + (row["hints"] or 0)
            t.add_row(row["date"], status_text(row["status"]),
                      str(row["solved_clues"]) if played else "",
                      str(row["wrong_guesses"]) if played else "",
                      f"{row['keystrokes']}/{row['minimum_keystrokes']}" if played else "",
                      percent(row["efficiency"]),
                      str(help_used) if played and help_used else "",
                      "✔" if row["solved_on_the_day"] else "")
        yield t

    emit(rows, fmt, table)


def history_rabbithole(start: FromOption = None, end: ToOption = None, fmt: FormatOption = None) -> None:
    """Your Rabbithole results: score and how you answered each question."""
    first, last = date_window(start, end, "rabbithole")
    client = state.client()
    puzzles = client.rabbithole_puzzles(first.isoformat(), last.isoformat())
    rows = views.rabbithole_results(puzzles, client.game_states([("rabbithole", p.date, p.id) for p in puzzles]))

    def table(data):
        t = Table(title=f"Rabbithole {first} to {last}", title_justify="left", header_style="bold")
        for column in ("Date", "ID", "Status", "Score", "Questions"):
            t.add_column(column, justify="right" if column in ("ID", "Score") else "left")
        for row in data:
            t.add_row(row["date"], row["id"], status_text(row["status"]),
                      f"{row['score']}/{row['max_score']}" if row["score"] is not None else "",
                      "".join(RESULT_ICONS.get(r, "?") for r in row["results"]))
        yield t
        yield Text("🟢 first try  🟡 with the hint  🟠 multiple choice  🔴 wrong", style="dim")

    emit(rows, fmt, table)


def history_crossword(
    series: SeriesOption = Series.daily,
    start: FromOption = None,
    end: ToOption = None,
    fmt: FormatOption = None,
) -> None:
    """Your crossword results from Amuse Labs: solved, time and help used.

    Makes one request per crossword.
    """
    first, last = date_window(start, end, "crossword")
    client = state.client()
    listings = client.crosswords(series.value, first.isoformat(), last.isoformat())
    if not listings and series == Series.daily:
        raise AtlanticGamesNotFoundError(f"No crosswords from {first} to {last}")
    rows = [views.crossword_result(item, client.crossword_play(item.puzzleId, series.value))
            for item in progress(listings, len(listings), "Fetching crosswords")]

    def table(data):
        name = "Caleb's Inferno" if series == Series.inferno else "Crosswords"
        t = Table(title=f"{name} {first} to {last}", title_justify="left", header_style="bold")
        for column in ("Date", "Author", "Status", "Entries", "Time", "Help"):
            t.add_column(column, justify="right" if column in ("Time", "Entries") else "left")
        for row in data:
            t.add_row(row["date"] or "", row["author"], status_text(row["status"]),
                      f"{row['correct_entries']}/{row['entries']}" if row["correct_entries"] is not None
                      and row["entries"] else "",
                      format_seconds(row["seconds"]) if row["seconds"] else "",
                      ", ".join(row["help"]))
        yield t

    emit(rows, fmt, table)
