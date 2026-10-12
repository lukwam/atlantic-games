"""atlg puzzle commands.

Answers are hidden unless --answers is given, in every output format.
"""
import enum
from pathlib import Path
from typing import Annotated
from typing import Optional

import typer
from rich.columns import Columns
from rich.table import Table
from rich.text import Text

from atlgames import AtlanticGamesExportError
from atlgames import AtlanticGamesNotFoundError
from atlgames import formats
from atlgames import views
from atlgames.cli.dates import parse_date
from atlgames.cli.output import FormatOption
from atlgames.cli.output import console
from atlgames.cli.output import emit
from atlgames.cli.state import date_arg
from atlgames.cli.state import state

DateArgument = Annotated[
    str,
    typer.Argument(help="YYYY-MM-DD, today, yesterday, tomorrow or a weekday.", show_default=True),
]
AnswersOption = Annotated[bool, typer.Option("--answers", "-a", help="Show the answers.")]

# Bracket City's nesting levels, outermost first.
DEPTH_STYLES = ["cyan", "magenta", "yellow", "blue", "red", "green"]
# Marks answers in rendered Bracket City text, so they can be styled.
MARK_START, MARK_END = "\x01", "\x02"


class Series(str, enum.Enum):
    daily = "daily"
    inferno = "inferno"


SeriesOption = Annotated[Series, typer.Option("--series", "-s", help="daily (the Crossword) or inferno "
                                                                      "(Caleb's Inferno).")]


def register(app: typer.Typer) -> None:
    """Add the puzzle commands to the root app."""
    app.command("bracket-city")(bracket_city)
    app.command("crossword")(crossword)
    app.command("rabbithole")(rabbithole)
    app.command("trivia")(trivia)
    app.command("stacks")(stacks)
    app.command("games")(games)
    lists = typer.Typer(help="List the puzzles a game has.", no_args_is_help=True)
    lists.command("bracket-city")(list_bracket_city)
    lists.command("crossword")(list_crossword)
    lists.command("rabbithole")(list_rabbithole)
    lists.command("trivia")(list_trivia)
    lists.command("stacks")(list_stacks)
    app.add_typer(lists, name="list")


def depth_style(depth: int) -> str:
    return DEPTH_STYLES[(depth - 1) % len(DEPTH_STYLES)]


def bracket_text(text: str, depth: int = 0) -> Text:
    """Render Bracket City text with each nesting level in its own color.

    `depth` is the level the text is at, for a clue shown on its own.
    Answers marked with MARK_START and MARK_END are shown in bold green.
    """
    result = Text()
    answer = False
    for char in text:
        if char == MARK_START:
            answer = True
        elif char == MARK_END:
            answer = False
        elif answer:
            result.append(char, style="bold green")
        elif char == "[":
            depth += 1
            result.append(char, style=f"bold {depth_style(depth)}")
        elif char == "]":
            result.append(char, style=f"bold {depth_style(depth)}")
            depth -= 1
        else:
            result.append(char, style=depth_style(depth) if depth else "")
    return result


def mark(answer: str) -> str:
    return f"{MARK_START}{answer}{MARK_END}"


def bracket_city(
    date: DateArgument = "today",
    answers: AnswersOption = False,
    clues: Annotated[bool, typer.Option("--clues", "-c", help="List the clues, innermost ones included.")] = False,
    steps: Annotated[bool, typer.Option("--steps", help="Show a solving order, one clue at a time "
                                                        "(shows the answers).")] = False,
    fmt: FormatOption = None,
) -> None:
    """Show a Bracket City puzzle: the bracketed text, solved with --answers.

    Play it here with [bold]atlg play bracket-city[/bold].
    """
    day = date_arg(date, "bracket-city")
    client = state.client()
    puzzle = client.bracket_city(None if date == "today" else day.isoformat())
    data = views.bracket_city_view(puzzle, answers, clues, steps)

    def table(data):
        yield Text(f"Bracket City {data['date']}" + (f" by {data['author']}" if data.get("author") else ""),
                   style="bold")
        yield Text(f"{data['clues']} clues, nested {data['depth']} deep", style="dim")
        yield Text()
        yield bracket_text(data["puzzle"])
        if "clue_list" in data:
            t = Table(title="Clues", title_justify="left", header_style="bold", box=None)
            t.add_column("#", justify="right")
            t.add_column("Clue")
            if answers:
                t.add_column("Answer", style="green")
            for clue in data["clue_list"]:
                cell = Text("  " * (clue["depth"] - 1)) + bracket_text(clue["clue"], clue["depth"])
                t.add_row(str(clue["number"]), cell, *([clue["answer"]] if answers else []))
            yield Text()
            yield t
        if "steps" in data:
            t = Table(title="Solving order", title_justify="left", header_style="bold", box=None)
            t.add_column("Step", justify="right")
            t.add_column("Clue")
            t.add_column("Answer", style="green")
            for step in data["steps"]:
                t.add_row(str(step["step"]), step["clue"], step["answer"])
            yield Text()
            yield t
        if "solution" in data:
            yield Text()
            yield bracket_text(mark(data["solution"]))
            if data.get("completion_text"):
                yield Text(data["completion_text"], style="italic")
            if data.get("completion_url"):
                yield Text(data["completion_url"], style="dim")

    emit(data, fmt, table)


def crossword_grid(puzzle, answers: bool) -> Text:
    """Render a crossword grid, with clue numbers or letters."""
    board = Text()
    for square in puzzle.squares():
        if square.block:
            board.append("███", style="grey30")
        else:
            style = "black on white" + (" underline" if square.circled else "")
            if square.shaded:
                style = "black on grey70"
            if answers:
                board.append(f" {square.answer[:1] or ' '} ", style="bold " + style)
            else:
                board.append(f"{square.label or '':<3}", style=style)
        if square.col == puzzle.w - 1:
            board.append("\n")
    return board


def save_crossword(puzzle, path: Path) -> None:
    """Save a crossword in the format matching the file extension."""
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in formats.FORMATS:
        raise typer.BadParameter(f"Use a .puz, .ipuz or .xml file name, not {path.name!r}.",
                                 param_hint="'--save'")
    try:
        data = formats.export(puzzle, fmt)
    except AtlanticGamesExportError as err:
        console.print(f"[red]Can't save this puzzle as .{fmt}:[/red] " + "; ".join(err.reasons))
        raise typer.Exit(1) from None
    path.write_bytes(data)
    console.print(f"Saved [bold]{path}[/bold]")
    for note in formats.fidelity(puzzle, fmt):
        console.print(f"[dim]Note: {note}[/dim]")


def crossword(
    date: DateArgument = "today",
    series: SeriesOption = Series.daily,
    answers: AnswersOption = False,
    clues: Annotated[bool, typer.Option(help="Show the clues.")] = True,
    puzzle_id: Annotated[
        Optional[str], typer.Option("--id", help="Show the crossword with this puzzle ID instead "
                                                 "(see atlg list crossword).")
    ] = None,
    save: Annotated[
        Optional[Path],
        typer.Option("--save", "-o", help="Save as a crossword file instead: .puz, .ipuz or .xml (Crossword Compiler).",
                     dir_okay=False),
    ] = None,
    fmt: FormatOption = None,
) -> None:
    """Show a crossword: the grid and clues, filled in with --answers.

    The Crossword is daily; Caleb's Inferno (--series inferno) is monthly, so
    give any date in its month or use --id.
    """
    day = date_arg(date, "crossword")
    client = state.client()
    if puzzle_id:
        puzzle = client.crossword(puzzle_id=puzzle_id, series=series.value)
    elif series == Series.inferno:
        puzzle = inferno_for(client, day)
    else:
        puzzle = client.crossword(None if date == "today" else day.isoformat(), series=series.value)
    if save:
        return save_crossword(puzzle, save)
    data = views.crossword_view(puzzle, answers, clues)

    def table(data):
        name = "Caleb's Inferno" if data["series"] == "atlantic-inferno" else "The Crossword"
        heading = f"{name} {data['date']}"
        if data.get("title") and data["title"] not in heading and data["date"] not in data["title"]:
            heading += f": {data['title']}"
        yield Text(heading, style="bold")
        yield Text(f"By {data['constructor']}" + (f" · Edited by {data['editor']}" if data.get("editor") else ""),
                   style="dim")
        if data.get("notes"):
            yield Text(data["notes"], style="italic")
        yield crossword_grid(puzzle, answers)
        if "clues" in data:
            panels = []
            for name, entries in data["clues"].items():
                t = Table(title=name.title(), title_justify="left", show_header=False, box=None)
                t.add_column(justify="right", style="bold")
                t.add_column(max_width=48)
                if answers:
                    t.add_column(style="green")
                for entry in entries:
                    t.add_row(entry["label"], entry["clue"], *([entry["answer"]] if answers else []))
                panels.append(t)
            yield Columns(panels, padding=(0, 4))

    emit(data, fmt, table)


def inferno_for(client, day):
    """Return the Inferno published on or before a date (it's monthly)."""
    listings = client.crosswords("inferno", date_end=day.isoformat(), limit=1)
    if not listings:
        raise AtlanticGamesNotFoundError(f"No Caleb's Inferno on or before {day}")
    return client.crossword(puzzle_id=listings[0].puzzleId, series="inferno")


def rabbithole_puzzle(client, value: str | None):
    """Return a Rabbithole puzzle by ID, by date, or the latest one."""
    if value is None or value == "today":
        return client.rabbithole()
    if value.isdigit():
        return client.rabbithole(value)
    day = date_arg(value, "rabbithole").isoformat()
    puzzles = client.rabbithole_puzzles(day, day)
    if not puzzles:
        raise AtlanticGamesNotFoundError(f"No Rabbithole puzzle for {day} (it's published on weekdays)")
    return puzzles[0]


RabbitholeArgument = Annotated[
    Optional[str],
    typer.Argument(help="A puzzle ID or a date (default: the latest).", show_default=False),
]


def rabbithole(puzzle: RabbitholeArgument = None, answers: AnswersOption = False,
               fmt: FormatOption = None) -> None:
    """Show a Rabbithole puzzle: its first question, or every question and answer with --answers.

    Each question names the previous answer, so only the first is shown
    without --answers. Play it here with [bold]atlg play rabbithole[/bold].
    """
    data = views.rabbithole_view(rabbithole_puzzle(state.client(), puzzle), answers)

    def table(data):
        yield Text(f"Rabbithole {data['date']} (#{data['id']})"
                   + (f" by {data['byline']}" if data.get("byline") else ""), style="bold")
        if "first_question" in data:
            yield Text(f"{data['questions']} questions, each leading to the next. The first:", style="dim")
            yield Text()
            yield Text(data["first_question"])
            return
        t = Table(header_style="bold", show_lines=True)
        t.add_column("#", justify="right")
        t.add_column("Question")
        t.add_column("Answer", style="green")
        for q in data["question_list"]:
            t.add_row(str(q["number"]), q["question"], q["answer"])
        yield t
        if data.get("article"):
            yield Text.assemble(("Article: ", "bold"), data["article"]["title"] or "", " ",
                                (data["article"]["url"] or "", "dim"))

    emit(data, fmt, table)


def trivia_article(client, value: str):
    """Return a Trivia article by date, ID or URL."""
    try:
        day = parse_date(value, "trivia").isoformat()
    except ValueError:
        return client.trivia(value)
    for listing in client.trivia_articles():
        if listing.date == day:
            return client.trivia(listing)
        if listing.date and listing.date < day:
            break
    raise AtlanticGamesNotFoundError(f"No Atlantic Trivia for {day} (it ran until 2026-08-14)")


def trivia(
    article: Annotated[str, typer.Argument(help="A date, article ID or URL; last for the last one.")] = "last",
    answers: AnswersOption = False,
    fmt: FormatOption = None,
) -> None:
    """Show a day's Atlantic Trivia questions, with answers if asked (the game ended on 2026-08-14)."""
    data = views.trivia_view(trivia_article(state.client(), article), answers)

    def table(data):
        yield Text(f"{data['title']} ({data['date']})", style="bold")
        if not data["questions"]:
            yield Text("This article has no questions (before 2026-03-13 Trivia was a weekly roundup).",
                       style="dim")
        for q in data["questions"]:
            yield Text()
            yield Text.assemble((f"{q['number']}. ", "bold"), (f"{q['topic']}: " if q["topic"] else "", "cyan"),
                                q["question"])
            if "answer" in q:
                yield Text(f"   {q['answer']}", style="bold green")
                if q.get("explanation"):
                    yield Text(f"   {q['explanation']}", style="dim")

    emit(data, fmt, table)


def stacks(
    date: Annotated[str, typer.Argument(help="YYYY-MM-DD, or first or last.")] = "last",
    answers: AnswersOption = False,
    fmt: FormatOption = None,
) -> None:
    """Show a Stacks puzzle: the words to drop, and the solution with --answers (2025-06-17 to 2026-08-24)."""
    puzzle = state.client().stacks(date_arg(date, "stacks").isoformat())
    data = views.stacks_view(puzzle, answers)

    def table(data):
        yield Text(f"Stacks {data['date']}" + (f": {data['title']}" if data.get("title") else ""), style="bold")
        yield Text.assemble(("Words: ", "bold"), "  ".join(w.upper() for w in data["words"]))
        base = Text()
        for letter in data["base"]:
            base.append(" · " if letter == "-" else f" {letter.upper()} ",
                        style="dim" if letter == "-" else "bold white on grey35")
        yield Text.assemble(("Base:  ", "bold"), base)
        if "drops" in data:
            yield Text.assemble(("Drops: ", "bold"), ", ".join(f"{d['word'].upper()} in column {d['column']}"
                                                              for d in data["drops"]))
            board = Text()
            for row in data["board"]:
                for letter in row:
                    board.append("   " if letter == " " else f" {letter.upper()} ",
                                 style="" if letter == " " else "bold black on green")
                board.append("\n")
            yield board

    emit(data, fmt, table)


def games(fmt: FormatOption = None) -> None:
    """List the games on The Atlantic's games hub."""
    data = [{"slug": g.slug, "name": g.name, "author": g.author, "archive": g.hasArchive,
             "featured": g.isFeaturedGame, "description": g.shortDescription, "url": g.url}
            for g in state.client().games()]

    def table(data):
        t = Table(header_style="bold")
        for column in ("Game", "Slug", "By", "Archive", "Description"):
            t.add_column(column)
        for g in data:
            t.add_row(g["name"], g["slug"], g["author"] or "", "yes" if g["archive"] else "",
                      g["description"] or "")
        yield t

    emit(data, fmt, table)


FromOption = Annotated[Optional[str], typer.Option("--from", help='First date, or "first".')]
ToOption = Annotated[Optional[str], typer.Option("--to", help="Last date.")]


def window(start: str | None, end: str | None, game: str) -> tuple[str | None, str | None]:
    first = date_arg(start, game).isoformat() if start else None
    last = date_arg(end, game).isoformat() if end else None
    if first and last and first > last:
        raise typer.BadParameter("--from is after --to")
    return first, last


def list_table(columns: list[str], title: str):
    def table(data):
        t = Table(title=title, title_justify="left", header_style="bold")
        for column in columns:
            t.add_column(column.replace("_", " ").title())
        for row in data:
            t.add_row(*("" if row.get(c) is None else str(row[c]) for c in columns))
        yield t
        yield Text(f"{len(data)} puzzles", style="dim")

    return table


def list_bracket_city(start: FromOption = None, end: ToOption = None, fmt: FormatOption = None) -> None:
    """List Bracket City's dates (the archive starts on 2025-01-01)."""
    first, last = window(start, end, "bracket-city")
    data = [{"date": d} for d in state.client().bracket_city_dates()
            if (not first or d >= first) and (not last or d <= last)]
    emit(data, fmt, list_table(["date"], "Bracket City"))


def list_crossword(
    series: SeriesOption = Series.daily,
    start: FromOption = None,
    end: ToOption = None,
    limit: Annotated[Optional[int], typer.Option("--limit", "-n", help="At most this many (default: 30 "
                                                                         "without --from).", min=1)] = None,
    fmt: FormatOption = None,
) -> None:
    """List crosswords, newest first, with their IDs."""
    first, last = window(start, end, "crossword")
    if limit is None and not first:
        limit = 30
    listings = state.client().crosswords(series.value, first, last, limit)
    data = [views.crossword_listing_row(item) for item in listings]
    name = "Caleb's Inferno" if series == Series.inferno else "The Crossword"
    emit(data, fmt, list_table(["date", "id", "title", "author", "size"], name))


def list_rabbithole(start: FromOption = None, end: ToOption = None, fmt: FormatOption = None) -> None:
    """List Rabbithole puzzles, newest first, with their IDs."""
    first, last = window(start, end, "rabbithole")
    data = [views.rabbithole_listing_row(p) for p in state.client().rabbithole_puzzles(first, last)]
    emit(data, fmt, list_table(["date", "id", "byline", "questions"], "Rabbithole"))


def list_trivia(
    limit: Annotated[Optional[int], typer.Option("--limit", "-n", help="At most this many.", min=1)] = None,
    fmt: FormatOption = None,
) -> None:
    """List Atlantic Trivia articles, newest first."""
    data = [views.trivia_listing_row(a) for a in state.client().trivia_articles(limit)]
    emit(data, fmt, list_table(["date", "id", "title"], "Atlantic Trivia"))


def list_stacks(fmt: FormatOption = None) -> None:
    """List every Stacks puzzle."""
    data = [{"date": p.date, "id": p.id, "title": p.title} for p in state.client().stacks_puzzles()]
    emit(data, fmt, list_table(["date", "id", "title"], "Stacks"))
