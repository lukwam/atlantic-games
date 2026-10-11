"""atlg archive: save puzzles as JSON files, one per date."""
import datetime
import enum
import functools
import hashlib
import json
import time
from pathlib import Path
from typing import Annotated
from typing import Optional

import typer
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import TextColumn
from rich.progress import TimeRemainingColumn

from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesClient
from atlgames import AtlanticGamesError
from atlgames import AtlanticGamesNotFoundError
from atlgames import AtlanticGamesExportError
from atlgames import __version__
from atlgames import formats
from atlgames.cli.dates import date_range
from atlgames.cli.output import FormatOption
from atlgames.cli.output import emit
from atlgames.cli.output import err_console
from atlgames.cli.output import key_value_table
from atlgames.cli.state import date_arg
from atlgames.cli.state import state


class ArchiveGame(str, enum.Enum):
    bracket_city = "bracket-city"
    crossword = "crossword"
    inferno = "inferno"
    rabbithole = "rabbithole"
    trivia = "trivia"
    stacks = "stacks"


# The dates games use for "first" and "last".
DATE_GAMES = {"inferno": "crossword"}


def archive_items(client: AtlanticGamesClient, game: ArchiveGame, days: list) -> tuple[list, list]:
    """Return the (date, file stem, fetch) items to archive, and dates known to have no puzzle.

    Each game's list of puzzles is fetched first, so dates without a puzzle
    are known without asking for them, and games keyed by ID (crosswords,
    Rabbithole, Trivia) are fetched by ID. A date with more than one puzzle
    is saved as YYYY-MM-DD-ID files.
    """
    first, last = days[0].isoformat(), days[-1].isoformat()
    wanted = [d.isoformat() for d in days]
    by_date: dict[str, list] = {}
    if game == ArchiveGame.bracket_city:
        for day in client.bracket_city_dates():
            if first <= day <= last:
                by_date[day] = [(day, functools.partial(client.bracket_city, day))]
    elif game in (ArchiveGame.crossword, ArchiveGame.inferno):
        series = "daily" if game == ArchiveGame.crossword else "inferno"
        for item in client.crosswords(series, first, last):
            by_date.setdefault(item.date, []).append(
                (item.puzzleId, functools.partial(client.crossword, puzzle_id=item.puzzleId, series=series)))
    elif game == ArchiveGame.rabbithole:
        for puzzle in client.rabbithole_puzzles(first, last):
            # The list already has every question and answer.
            by_date.setdefault(puzzle.date, []).append((puzzle.id, functools.partial(lambda p: p, puzzle)))
    elif game == ArchiveGame.trivia:
        for article in client.trivia_articles():
            if article.date and article.date < first:
                break
            if article.date and article.date <= last:
                by_date.setdefault(article.date, []).append(
                    (article.article_id, functools.partial(client.trivia, article)))
    else:
        puzzles = {p.date: p for p in client.stacks_puzzles()}
        for day in wanted:
            if day in puzzles:
                by_date[day] = [(day, functools.partial(lambda p: p, puzzles[day]))]
    items, missing = [], []
    for day in wanted:
        found = by_date.get(day)
        if not found:
            missing.append(day)
            continue
        for key, fetch in found:
            stem = day if len(found) == 1 else f"{day}-{key}"
            items.append((day, stem, fetch))
    return items, missing


def archive(
    game: Annotated[ArchiveGame, typer.Argument(help="The game to archive.")],
    start: Annotated[str, typer.Option("--from", help='First date, or "first" for the first puzzle.')] = "today",
    end: Annotated[str, typer.Option("--to", help='Last date, or "last" for games that have ended.')] = "today",
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory to save into.",
                                      file_okay=False)] = Path("atlantic-archive"),
    delay: Annotated[float, typer.Option(help="Seconds to wait between requests.", min=0)] = 0.25,
    overwrite: Annotated[bool, typer.Option(help="Download dates that are already saved.")] = False,
    file_format: Annotated[
        str, typer.Option("--as", help="File format: json, or for crosswords puz, ipuz or xml.")
    ] = "json",
    fmt: FormatOption = None,
) -> None:
    """Save each date's puzzle in OUT/GAME/YYYY-MM-DD.json (or .puz, .ipuz, .xml).

    Dates already saved are skipped, so an interrupted archive can be resumed
    by running the same command again. Dates without a puzzle are reported as
    missing (Rabbithole is published on weekdays, Caleb's Inferno monthly).

    OUT/GAME/manifest.json records when each file was fetched, the
    atlantic-games version and a SHA-256 hash. With --overwrite, a puzzle
    that has changed since it was saved keeps its previous version in
    OUT/GAME/revisions/ and is listed as updated.
    """
    crossword = game in (ArchiveGame.crossword, ArchiveGame.inferno)
    if file_format != "json" and (not crossword or file_format not in formats.FORMATS):
        raise typer.BadParameter("Use json, or puz, ipuz or xml for crosswords.", param_hint="'--as'")
    date_game = DATE_GAMES.get(game.value, game.value)
    first = date_arg(start, date_game)
    last = date_arg(end, date_game)
    if first > last:
        raise typer.BadParameter("--from is after --to")
    directory = out / game.value
    directory.mkdir(parents=True, exist_ok=True)
    days = list(date_range(first, last))
    items, missing = archive_items(state.client(), game, days)
    result: dict[str, Optional[object]] = {"game": game.value, "directory": str(directory),
                                           "format": file_format, "saved": 0, "skipped": 0,
                                           "updated": [], "missing": missing, "unsupported": [],
                                           "errors": []}
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": {}}
    columns = (TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn())
    try:
        archive_days(items, directory, file_format, overwrite, delay, manifest, result,
                     Progress(*columns, console=err_console, transient=True), game)
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def table(data):
        yield key_value_table({
            "Saved": data["saved"],
            "Already saved": data["skipped"],
            "Changed since saved": ", ".join(data["updated"]) if len(data["updated"]) <= 5
            else f"{len(data['updated'])} dates",
            "No puzzle": ", ".join(data["missing"]) if len(data["missing"]) <= 5
            else f"{len(data['missing'])} dates",
            "Can't save as " + data["format"]: len(data["unsupported"]),
            "Errors": len(data["errors"]),
            "Directory": data["directory"],
        }, title=f"[bold]Archived {data['game']}[/bold]")

    emit(result, fmt, table)
    if result["errors"]:
        raise typer.Exit(1)


def archive_days(items, directory: Path, file_format: str, overwrite: bool, delay: float,
                 manifest: dict, result: dict, progress_bar: Progress, game: ArchiveGame) -> None:
    """Fetch and save each item, updating the manifest and result."""
    with progress_bar as progress:
        task = progress.add_task(f"Archiving {game.value}", total=len(items))
        for day, stem, fetch in items:
            path = directory / f"{stem}.{file_format}"
            if path.exists() and not overwrite:
                result["skipped"] += 1
                progress.advance(task)
                continue
            try:
                puzzle = fetch()
            except AtlanticGamesAuthenticationError:
                raise
            except AtlanticGamesNotFoundError:
                result["missing"].append(day)
            except AtlanticGamesError as err:
                result["errors"].append({"date": day, "error": str(err)})
            else:
                if file_format == "json":
                    content = (json.dumps(puzzle.model_dump(mode="json", by_alias=True),
                                          ensure_ascii=False, indent=2) + "\n").encode()
                else:
                    try:
                        content = formats.export(puzzle, file_format)
                    except AtlanticGamesExportError as err:
                        result["unsupported"].append({"date": stem, "reasons": err.reasons})
                        content = None
                if content is not None:
                    save(path, content, day, puzzle, manifest, result)
            progress.advance(task)
            if delay:
                time.sleep(delay)


def save(path: Path, content: bytes, day: str, puzzle, manifest: dict, result: dict) -> None:
    """Write a file atomically and record it in the manifest.

    If a puzzle has changed since it was saved, the previous file is kept in
    revisions/ first.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    digest = hashlib.sha256(content).hexdigest()
    previous = manifest["files"].get(path.name)
    revisions = previous.get("revisions", []) if previous else []
    if path.exists():
        old_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if old_digest != digest:
            fetched = (previous or {}).get("retrieved_at", "unknown").replace(":", "")
            revision = path.parent / "revisions" / f"{path.stem}.{fetched}{path.suffix}"
            revision.parent.mkdir(exist_ok=True)
            path.replace(revision)
            revisions.append({"file": f"revisions/{revision.name}", "sha256": old_digest,
                              "retrieved_at": (previous or {}).get("retrieved_at")})
            result["updated"].append(day)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
    manifest["files"][path.name] = {
        "date": day,
        "puzzle_id": str(getattr(puzzle, "id", "") or "") or None,
        "retrieved_at": now,
        "sha256": digest,
        "atlantic_games": __version__,
        **({"revisions": revisions} if revisions else {}),
    }
    result["saved"] += 1
