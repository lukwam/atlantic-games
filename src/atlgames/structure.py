"""Crossword structure: squares and entries, shaped like nytimes-games'.

Use the methods on the model: ``CrosswordPuzzle.squares()`` and
``CrosswordPuzzle.entries()``. Amuse Labs stores the grid column-major
(``box[x][y]``); everything here is row-major, with (row, col) from 0.
"""
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from atlgames.models import CrosswordPuzzle


@dataclass(frozen=True)
class Square:
    """One square of a crossword grid."""

    index: int
    row: int
    col: int
    block: bool
    #: The square's answer; more than one letter for a rebus.
    answer: str = ""
    label: str | None = None
    circled: bool = False
    shaded: bool = False

    @property
    def rebus(self) -> bool:
        return len(self.answer) > 1


@dataclass(frozen=True)
class Entry:
    """One crossword entry: a clue and the squares of its answer."""

    #: For example "17-Across".
    id: str
    number: int | None
    label: str | None
    direction: str
    #: The clue as Amuse Labs stores it, which can include HTML such as <i>.
    clue: str
    answer: str
    cells: tuple[int, ...]
    coordinates: tuple[tuple[int, int], ...]
    crossings: tuple[str, ...] = field(default=())


def _cell_infos(puzzle: "CrosswordPuzzle") -> dict[tuple[int, int], dict]:
    infos = getattr(puzzle, "cellInfos", None) or []
    result = {}
    for info in infos:
        if isinstance(info, dict) and "x" in info and "y" in info:
            result[(info["y"], info["x"])] = info
    return result


def crossword_squares(puzzle: "CrosswordPuzzle") -> list[Square]:
    """Every square, row by row."""
    infos = _cell_infos(puzzle)
    squares = []
    for row in range(puzzle.h):
        for col in range(puzzle.w):
            block = puzzle.is_block(row, col)
            label = None
            if puzzle.clueNums and col < len(puzzle.clueNums) and row < len(puzzle.clueNums[col]):
                # Older puzzles use "0" for squares without a number.
                label = puzzle.clueNums[col][row] or None
                if label == "0":
                    label = None
            info = infos.get((row, col), {})
            squares.append(Square(
                index=row * puzzle.w + col, row=row, col=col, block=block,
                answer="" if block else (puzzle.box[col][row] or ""),
                label=None if block else label,
                circled=bool(info.get("isCircled")),
                shaded=bool(info.get("bgColor")) and not block,
            ))
    return squares


def crossword_entries(puzzle: "CrosswordPuzzle") -> list[Entry]:
    """Every entry, Across then Down, in clue number order."""
    raw = []
    for word in puzzle.placedWords:
        direction = "Across" if word.acrossNotDown else "Down"
        coords = tuple((word.y, word.x + i) if word.acrossNotDown else (word.y + i, word.x)
                       for i in range(word.nBoxes))
        cells = tuple(r * puzzle.w + c for r, c in coords)
        try:
            number = int(word.clueNum) if word.clueNum is not None else None
        except ValueError:
            number = None
        label = word.clueNum
        entry_id = f"{label}-{direction}" if label else f"{direction}-{len(raw) + 1}"
        answer = "".join(puzzle.box[c][r] or "" for r, c in coords)
        raw.append((entry_id, number, label, direction, word.clue.clue, answer, cells, coords))
    by_cell: dict[int, list[str]] = {}
    for item in raw:
        for cell in item[6]:
            by_cell.setdefault(cell, []).append(item[0])
    entries = []
    for entry_id, number, label, direction, clue, answer, cells, coords in raw:
        crossings = tuple(dict.fromkeys(other for cell in cells for other in by_cell[cell] if other != entry_id))
        entries.append(Entry(entry_id, number, label, direction, clue, answer, cells, coords, crossings))
    entries.sort(key=lambda e: (e.direction != "Across", e.number if e.number is not None else 1 << 30))
    return entries
