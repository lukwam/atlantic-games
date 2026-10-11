"""Export Atlantic crosswords to standard crossword file formats.

- ``ipuz``: the open JSON format (http://ipuz.org)
- ``puz``: Across Lite's binary format, the most widely supported
- ``xml``: Crossword Compiler's rectangular-puzzle XML
  (https://crossword.info/xml/rectangular-puzzle.xsd)

Works with both series: the daily Crossword and Caleb's Inferno. Your saved
progress isn't included: Amuse Labs' saved play (``CrosswordPlay``) doesn't
carry the letters you've filled in.

Puzzles with gimmicks the formats can't represent, such as squares labeled
with text or entries that run off the grid, raise AtlanticGamesExportError
with the reasons. Use ``export_problems()`` to check without exporting, and
``fidelity()`` to see what an export approximates, such as italics in clues
or shading shown as circles in .puz.

The puzzles are copyrighted by The Atlantic and hosted by Amuse Labs;
exported files are for personal use.
"""
import datetime
import json
import re
import struct
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from dataclasses import field

from atlgames.exceptions import AtlanticGamesExportError
from atlgames.models import CrosswordPuzzle
from atlgames.models import CrosswordSeries
from atlgames.models import strip_html

FORMATS = ("ipuz", "puz", "xml")
MEDIA_TYPES = {
    "ipuz": "application/json",
    "puz": "application/x-crossword",
    "xml": "application/xml",
}
SHADE_COLOR = "D3D3D3"
PUBLISHER = "The Atlantic"
SERIES_NAMES = {
    CrosswordSeries.daily.value: "The Atlantic Crossword",
    CrosswordSeries.inferno.value: "Caleb's Inferno",
}
_HTML_TAG = re.compile(r"<\s*[a-zA-Z]")
_COLOR = re.compile(r"#?([0-9a-fA-F]{6})")


@dataclass
class Square:
    """One square of the grid."""
    block: bool
    solution: str = ""
    label: int | None = None
    circled: bool = False
    shaded: bool = False
    color: str = SHADE_COLOR


@dataclass
class Clue:
    number: int
    text: str
    cells: list[int]


@dataclass
class Grid:
    """A crossword in a format-neutral shape."""
    width: int
    height: int
    squares: list[Square]
    across: list[Clue]
    down: list[Clue]
    title: str
    author: str
    editor: str
    copyright: str
    date: datetime.date | None
    notes: str
    puzzle_id: str = ""
    series: str = CrosswordSeries.daily.value
    problems: list[str] = field(default_factory=list)

    def xy(self, index: int) -> tuple[int, int]:
        """Return the (column, row) of a square, from 0."""
        return index % self.width, index // self.width


def series_of(puzzle: CrosswordPuzzle) -> str:
    """The puzzle's Amuse Labs series, guessed from its ID if the client didn't set it."""
    if puzzle.series:
        return puzzle.series
    return CrosswordSeries.inferno.value if puzzle.id.startswith("inferno") else CrosswordSeries.daily.value


def default_title(puzzle: CrosswordPuzzle) -> str:
    """For example "The Atlantic Crossword: Saturday, October 10, 2026"."""
    name = SERIES_NAMES.get(series_of(puzzle), "The Atlantic Crossword")
    title = " ".join(puzzle.title.split())
    if title:
        return f"{name}: {title}"
    return f"{name}, {puzzle.date}" if puzzle.date else name


def cell_infos(puzzle: CrosswordPuzzle) -> dict[tuple[int, int], dict]:
    """Amuse Labs' per-square styles (circles and shading), keyed by (row, col)."""
    infos = getattr(puzzle, "cellInfos", None) or []
    return {(info["y"], info["x"]): info for info in infos
            if isinstance(info, dict) and "x" in info and "y" in info}


def rectangular(puzzle: CrosswordPuzzle) -> bool:
    return (puzzle.w > 0 and puzzle.h > 0 and len(puzzle.box) == puzzle.w
            and all(len(column) == puzzle.h for column in puzzle.box))


def to_grid(puzzle: CrosswordPuzzle, title: str | None = None) -> Grid:
    """Convert a puzzle to a Grid, noting gimmicks."""
    width, height = puzzle.w, puzzle.h
    problems = []
    squares = []
    lists = {"across": [], "down": []}
    if not rectangular(puzzle):
        problems.append("a grid that isn't rectangular")
    else:
        infos = cell_infos(puzzle)
        text_labels = []
        for row in range(height):
            for col in range(width):
                if puzzle.is_block(row, col):
                    squares.append(Square(block=True))
                    continue
                label = None
                if col < len(puzzle.clueNums) and row < len(puzzle.clueNums[col]):
                    label = puzzle.clueNums[col][row]
                if label and not label.isdigit():
                    text_labels.append(label)
                info = infos.get((row, col), {})
                color = _COLOR.fullmatch(str(info.get("bgColor") or "").strip())
                squares.append(Square(
                    block=False,
                    solution=puzzle.box[col][row] or "",
                    circled=bool(info.get("isCircled")),
                    shaded=bool(info.get("bgColor")),
                    color=color.group(1).upper() if color else SHADE_COLOR,
                ))
        if text_labels:
            problems.append(f"squares labeled with text ({' '.join(dict.fromkeys(text_labels))})")

        for word in puzzle.placedWords:
            name = "across" if word.acrossNotDown else "down"
            direction = name.capitalize()
            label = (word.clueNum or "").strip()
            if not label.isdigit():
                problems.append("clues without numbers")
                continue
            coords = [(word.y, word.x + i) if word.acrossNotDown else (word.y + i, word.x)
                      for i in range(word.nBoxes)]
            if word.nBoxes < 1 or any(not (0 <= r < height and 0 <= c < width) for r, c in coords):
                problems.append(f"{label}-{direction} runs outside the grid")
                continue
            cells = [r * width + c for r, c in coords]
            if any(squares[cell].block for cell in cells):
                problems.append(f"{label}-{direction} runs over a black square")
                continue
            lists[name].append(Clue(int(label), strip_html(word.clue.clue) or "", cells))
        for clues in lists.values():
            clues.sort(key=lambda clue: clue.number)
            for clue in clues:
                squares[clue.cells[0]].label = clue.number

    date = datetime.date.fromisoformat(puzzle.date) if puzzle.date else None
    return Grid(
        width=width,
        height=height,
        squares=squares,
        across=lists["across"],
        down=lists["down"],
        title=title or default_title(puzzle),
        author=puzzle.constructor,
        editor=puzzle.editor or "",
        copyright=" ".join(puzzle.copyright.split()) or f"© {PUBLISHER}",
        date=date,
        notes=strip_html(puzzle.description) or "",
        puzzle_id=puzzle.id,
        series=series_of(puzzle),
        problems=list(dict.fromkeys(problems)),
    )


def check(grid: Grid, fmt: str) -> None:
    if grid.problems:
        raise AtlanticGamesExportError(fmt, grid.problems)


def export_problems(puzzle: CrosswordPuzzle, fmt: str) -> list[str]:
    """Return why a puzzle can't be exported to a format, or [] if it can."""
    try:
        export(puzzle, fmt)
    except AtlanticGamesExportError as err:
        return err.reasons
    return []


def plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def fidelity(puzzle: CrosswordPuzzle, fmt: str) -> list[str]:
    """Return what exporting to a format approximates or leaves out.

    An empty list means the export keeps everything. Raises
    AtlanticGamesExportError if the puzzle can't be exported at all.
    """
    export(puzzle, fmt)
    grid = to_grid(puzzle)
    notes = []

    formatted = sum(1 for word in puzzle.placedWords if _HTML_TAG.search(word.clue.clue))
    if formatted:
        notes.append(f"clue formatting such as italics is dropped ({plural(formatted, 'clue')})")

    shaded = sum(square.shaded for square in grid.squares)
    if fmt == "puz":
        if shaded:
            notes.append("1 shaded square is shown as a circle" if shaded == 1
                         else f"{shaded} shaded squares are shown as circles")
        texts = [grid.title, grid.author, grid.copyright, grid.notes] + [
            clue.text for clue in grid.across + grid.down]
        converted = sorted({ch for text in texts for ch in text if ch in PUNCTUATION_CHARACTERS})
        if converted:
            notes.append(f"typographic punctuation is converted to plain text ({' '.join(converted)})")
    return notes


def export(puzzle: CrosswordPuzzle, fmt: str, title: str | None = None) -> bytes:
    """Export a puzzle to ipuz, puz or xml, as the bytes of the file."""
    if fmt == "ipuz":
        return json.dumps(to_ipuz(puzzle, title), ensure_ascii=False, indent=2).encode() + b"\n"
    if fmt == "puz":
        return to_puz(puzzle, title)
    if fmt == "xml":
        return to_xml(puzzle, title).encode()
    raise ValueError(f"Unknown format {fmt!r}; use one of {', '.join(FORMATS)}")


# ipuz


def to_ipuz(puzzle: CrosswordPuzzle, title: str | None = None) -> dict:
    """Return the puzzle as an ipuz document (a dict to save as JSON)."""
    grid = to_grid(puzzle, title)
    check(grid, "ipuz")

    def rows(values):
        return [values[r * grid.width:(r + 1) * grid.width] for r in range(grid.height)]

    cells = []
    for square in grid.squares:
        if square.block:
            cells.append("#")
            continue
        style = {}
        if square.circled:
            style["shapebg"] = "circle"
        if square.shaded:
            style["color"] = square.color
        cells.append({"cell": square.label or 0, "style": style} if style else square.label or 0)

    document = {
        "version": "http://ipuz.org/v2",
        "kind": ["http://ipuz.org/crossword#1"],
        "title": grid.title,
        "author": grid.author,
        "editor": grid.editor,
        "copyright": grid.copyright,
        "publisher": PUBLISHER,
        "origin": "atlantic-games",
        "dimensions": {"width": grid.width, "height": grid.height},
        "block": "#",
        "empty": 0,
        "puzzle": rows(cells),
        "solution": rows(["#" if s.block else s.solution for s in grid.squares]),
        "clues": {
            "Across": [[clue.number, clue.text] for clue in grid.across],
            "Down": [[clue.number, clue.text] for clue in grid.down],
        },
    }
    if grid.date:
        document["date"] = f"{grid.date:%m/%d/%Y}"
    if grid.notes:
        document["notes"] = grid.notes
    return document


# Across Lite .puz

PUNCTUATION_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "--", "…": "...", " ": " ",
}
PUNCTUATION = str.maketrans(PUNCTUATION_MAP)
PUNCTUATION_CHARACTERS = set(PUNCTUATION_MAP) - {" "}


def latin1(text: str, what: str, problems: list[str]) -> bytes:
    """Encode text as .puz's Latin-1, replacing common typographic punctuation."""
    text = unicodedata.normalize("NFC", text.translate(PUNCTUATION))
    try:
        return text.encode("latin-1")
    except UnicodeEncodeError:
        bad = sorted({ch for ch in text if ord(ch) > 255})
        problems.append(f"{what} with characters .puz can't store ({''.join(bad)})")
        return b""


def checksum(data: bytes, value: int = 0) -> int:
    """The .puz checksum."""
    for byte in data:
        value = ((value >> 1) | 0x8000) if value & 1 else value >> 1
        value = (value + byte) & 0xFFFF
    return value


def numbering(grid: Grid) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return the (number, first square) of each across and down entry, as .puz numbers them."""
    across, down = [], []
    number = 0
    for index, square in enumerate(grid.squares):
        if square.block:
            continue
        x, y = grid.xy(index)
        starts_across = (x == 0 or grid.squares[index - 1].block) and (
            x + 1 < grid.width and not grid.squares[index + 1].block)
        starts_down = (y == 0 or grid.squares[index - grid.width].block) and (
            y + 1 < grid.height and not grid.squares[index + grid.width].block)
        if starts_across or starts_down:
            number += 1
            if starts_across:
                across.append((number, index))
            if starts_down:
                down.append((number, index))
    return across, down


def section(name: bytes, data: bytes) -> bytes:
    return name + struct.pack("<HH", len(data), checksum(data)) + data + b"\0"


def to_puz(puzzle: CrosswordPuzzle, title: str | None = None) -> bytes:
    """Return the puzzle as an Across Lite .puz file."""
    grid = to_grid(puzzle, title)
    problems = list(grid.problems)

    across, down = numbering(grid)
    expected = [(n, i) for n, i in across] + [(n, i) for n, i in down]
    actual = [(c.number, c.cells[0]) for c in grid.across] + [(c.number, c.cells[0]) for c in grid.down]
    if not problems and sorted(expected) != sorted(actual):
        problems.append("numbering or entries that don't follow standard crossword rules")
    if grid.width > 255 or grid.height > 255:
        problems.append("a grid larger than 255 squares across")

    solution, fill = bytearray(), bytearray()
    rebus_answers: dict[str, int] = {}
    rebus = bytearray()
    for square in grid.squares:
        if square.block:
            solution += b"."
            fill += b"."
            rebus += b"\0"
            continue
        answer = square.solution.upper() or "X"
        letter = latin1(answer[0], "answers", problems)[:1] or b"X"
        solution += letter
        fill += b"-"
        if len(answer) > 1:
            rebus += bytes([rebus_answers.setdefault(answer, len(rebus_answers)) + 1])
        else:
            rebus += b"\0"

    clues = sorted(
        [(c.number, 0, c.text) for c in grid.across] + [(c.number, 1, c.text) for c in grid.down]
    )
    byline = f"{grid.author} / Edited by {grid.editor}" if grid.editor else grid.author
    strings = [latin1(grid.title, "the title", problems), latin1(byline, "the byline", problems),
               latin1(grid.copyright, "the copyright", problems)]
    clue_bytes = [latin1(text, "clues", problems) for _, _, text in clues]
    notes = latin1(grid.notes, "the notes", problems)
    if problems:
        raise AtlanticGamesExportError("puz", list(dict.fromkeys(problems)))

    def text_checksum(value: int) -> int:
        for string in strings:
            if string:
                value = checksum(string + b"\0", value)
        for clue in clue_bytes:
            value = checksum(clue, value)
        if notes:
            value = checksum(notes + b"\0", value)
        return value

    cib = struct.pack("<BBHHH", grid.width, grid.height, len(clue_bytes), 1, 0)
    c_cib = checksum(cib)
    c_solution = checksum(solution)
    c_fill = checksum(fill)
    c_text = text_checksum(0)
    overall = text_checksum(checksum(fill, checksum(solution, c_cib)))
    masked_low = bytes(a ^ (c & 0xFF) for a, c in zip(b"ICHE", (c_cib, c_solution, c_fill, c_text)))
    masked_high = bytes(a ^ (c >> 8) for a, c in zip(b"ATED", (c_cib, c_solution, c_fill, c_text)))

    header = (struct.pack("<H", overall) + b"ACROSS&DOWN\0" + struct.pack("<H", c_cib)
              + masked_low + masked_high + b"1.3\0" + b"\0\0" + b"\0\0" + b"\0" * 12 + cib)
    body = bytes(solution) + bytes(fill)
    body += b"".join(s + b"\0" for s in strings) + b"".join(c + b"\0" for c in clue_bytes) + notes + b"\0"

    extensions = b""
    if rebus_answers:
        table = "".join(f"{n:2d}:{answer};" for answer, n in sorted(rebus_answers.items(), key=lambda a: a[1]))
        extensions += section(b"GRBS", bytes(rebus))
        extensions += section(b"RTBL", latin1(table, "rebus answers", problems))
    flags = bytes(0x80 if s.circled or s.shaded else 0 for s in grid.squares)
    if any(flags):
        extensions += section(b"GEXT", flags)
    return header + body + extensions


# Crossword Compiler XML

XML_NAMESPACE = "http://crossword.info/xml/rectangular-puzzle"


def to_xml(puzzle: CrosswordPuzzle, title: str | None = None) -> str:
    """Return the puzzle as Crossword Compiler rectangular-puzzle XML."""
    grid = to_grid(puzzle, title)
    check(grid, "xml")
    ET.register_namespace("", XML_NAMESPACE)

    def tag(name: str) -> str:
        return f"{{{XML_NAMESPACE}}}{name}"

    root = ET.Element(tag("rectangular-puzzle"))
    metadata = ET.SubElement(root, tag("metadata"))
    url = f"urn:amuselabs:{grid.series}:{grid.puzzle_id}"
    for name, value in (("title", grid.title), ("created", grid.date.isoformat() if grid.date else ""),
                        ("creator", grid.author), ("editor", grid.editor), ("rights", ""),
                        ("copyright", grid.copyright), ("publisher", PUBLISHER),
                        ("identifier", url), ("description", grid.notes)):
        ET.SubElement(metadata, tag(name)).text = value

    crossword = ET.SubElement(root, tag("crossword"))
    grid_element = ET.SubElement(crossword, tag("grid"), width=str(grid.width), height=str(grid.height))
    ET.SubElement(grid_element, tag("grid-look"), {
        "numbering-scheme": "normal", "grid-line-color": "#000000", "block-color": "#000000",
        "font-color": "#000000", "number-color": "#000000",
    })
    for index, square in enumerate(grid.squares):
        x, y = grid.xy(index)
        attributes = {"x": str(x + 1), "y": str(y + 1)}
        if square.block:
            attributes["type"] = "block"
        else:
            attributes["solution"] = square.solution
            if square.label is not None:
                attributes["number"] = str(square.label)
            if square.circled:
                attributes["background-shape"] = "circle"
            if square.shaded:
                attributes["background-color"] = f"#{square.color}"
        ET.SubElement(grid_element, tag("cell"), attributes)

    words = []
    for clues in (grid.across, grid.down):
        for clue in clues:
            xs = sorted({grid.xy(c)[0] + 1 for c in clue.cells})
            ys = sorted({grid.xy(c)[1] + 1 for c in clue.cells})
            words.append((clue, f"{xs[0]}-{xs[-1]}" if len(xs) > 1 else str(xs[0]),
                          f"{ys[0]}-{ys[-1]}" if len(ys) > 1 else str(ys[0])))
    for word_id, (_, x, y) in enumerate(words, start=1):
        ET.SubElement(crossword, tag("word"), id=str(word_id), x=x, y=y)
    word_id = 1
    for name, clues in (("Across", grid.across), ("Down", grid.down)):
        container = ET.SubElement(crossword, tag("clues"), ordering="normal")
        heading = ET.SubElement(ET.SubElement(container, tag("title")), tag("b"))
        heading.text = name
        for clue in clues:
            element = ET.SubElement(container, tag("clue"), word=str(word_id), number=str(clue.number))
            element.text = clue.text
            word_id += 1
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
