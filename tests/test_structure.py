"""Crossword structure, on decoded Amuse Labs puzzles."""
import pytest

from atlgames import amuse
from atlgames.models import CrosswordPuzzle
from tests.support import crossword_params


def puzzle(name: str = "atlantic_20261010", **changes) -> CrosswordPuzzle:
    data = amuse.decode_rawc(crossword_params(name)["rawc"])
    data.update(changes)
    return CrosswordPuzzle(**data)


def test_grid_is_row_major():
    grid = puzzle().grid()
    assert ["".join(c or "#" for c in row) for row in grid[:3]] == ["##JAFAR###", "#MOMBLOG##", "MAKEITBIG#"]


def test_squares():
    p = puzzle()
    squares = p.squares()
    assert len(squares) == 100
    assert squares[0].block and squares[0].label is None and squares[0].answer == ""
    jafar = squares[2]
    assert (jafar.index, jafar.row, jafar.col, jafar.answer, jafar.label, jafar.block) == (2, 0, 2, "J", "1", False)
    assert sum(s.block for s in squares) == 28
    assert not any(s.rebus or s.circled or s.shaded for s in squares)


def test_entries():
    entries = {e.id: e for e in puzzle().entries()}
    assert len(entries) == 28
    across = entries["1-Across"]
    assert (across.number, across.label, across.direction, across.answer) == (1, "1", "Across", "JAFAR")
    assert across.clue.startswith("<i>Aladdin</i>")
    assert across.coordinates == ((0, 2), (0, 3), (0, 4), (0, 5), (0, 6))
    assert across.cells == (2, 3, 4, 5, 6)
    down = entries[across.crossings[0]]
    assert down.direction == "Down" and down.answer[0] == "J"
    ids = list(entries)
    assert ids.index("1-Across") < ids.index("8-Across") < ids.index(across.crossings[0])
    # Every square of every entry agrees with the grid.
    grid = puzzle().grid()
    for entry in entries.values():
        assert entry.answer == "".join(grid[r][c] for r, c in entry.coordinates)
        for other in entry.crossings:
            assert set(entries[other].cells) & set(entry.cells)


@pytest.mark.parametrize("name", ["2fbb3c8f", "inferno_20260517"])
def test_entries_cover_every_letter(name):
    p = puzzle(name)
    covered = {cell for entry in p.entries() for cell in entry.cells}
    assert covered == {s.index for s in p.squares() if not s.block}


def test_circled_shaded_and_rebus_squares():
    p = puzzle(cellInfos=[{"x": 2, "y": 0, "isCircled": True}, {"x": 3, "y": 0, "bgColor": "#ccc"},
                          {"x": 0, "y": 0, "bgColor": "#ccc"}, "junk"])
    p.box[4][0] = "FA"
    squares = p.squares()
    assert squares[2].circled and not squares[2].shaded
    assert squares[3].shaded
    assert not squares[0].shaded  # black squares aren't shaded
    assert squares[4].rebus and squares[4].answer == "FA"
    assert {e.id: e for e in p.entries()}["1-Across"].answer == "JAFAAR"


def test_entries_without_numbers():
    p = puzzle()
    p.placedWords[0].clueNum = None
    p.placedWords[1].clueNum = "A"
    entries = p.entries()
    unnumbered = [e for e in entries if e.number is None]
    assert {e.id for e in unnumbered} == {"Across-1", "A-Across"}
    across = [e for e in entries if e.direction == "Across"]
    assert entries[:len(across)] == across  # Across first
    assert {e.id for e in across[-2:]} == {"Across-1", "A-Across"}  # unnumbered last
