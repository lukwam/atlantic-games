"""Bracket City structure, checked on real puzzles."""
import pytest

from atlgames import AtlanticGamesParseError
from atlgames.bracket_city import Tree
from atlgames.models import BracketCityPuzzle
from tests.support import bracket_city_puzzle
from tests.support import bracket_city_puzzles

PUZZLES = bracket_city_puzzles()
#: Puzzles whose puzzleSolution caption differs from the text the game ends on.
CAPTION_MISMATCHES = {
    "2025-01-13", "2025-02-07", "2025-02-08", "2025-02-15", "2025-02-25", "2025-02-27", "2025-02-28",
    "2025-03-08", "2025-03-19", "2025-03-22", "2025-03-26", "2025-04-04", "2025-04-06", "2025-05-18",
    "2025-07-01", "2025-07-23", "2025-11-27", "2025-12-14", "2025-12-29", "2026-01-04", "2026-03-21",
    "2026-06-30",
}


@pytest.fixture(params=PUZZLES, ids=[p["puzzleDate"] for p in PUZZLES])
def puzzle(request) -> BracketCityPuzzle:
    return BracketCityPuzzle(**request.param)


def test_every_clue_has_its_answer(puzzle):
    clues = puzzle.clues()
    assert len(clues) == len(puzzle.solutions)
    assert {clue.text: clue.answer for clue in clues} == puzzle.solutions
    for clue in clues:
        assert "[" not in clue.text and "]" not in clue.text
        assert clue.raw.count("[") == clue.raw.count("]") == sum(1 for c in clues if _inside(clues, c, clue))
        if clue.parent is not None:
            parent = clues[clue.parent]
            assert clue.index in parent.children and clue.depth == parent.depth + 1
            assert clue.answer in parent.text
        else:
            assert clue.depth == 1
        assert clue.leaf == (not clue.children)


def _inside(clues, clue, ancestor) -> bool:
    while clue.parent is not None:
        clue = clues[clue.parent]
        if clue.index == ancestor.index:
            return True
    return False


def test_steps_solve_the_puzzle(puzzle):
    steps = puzzle.steps()
    assert sorted(c.index for c in steps) == list(range(len(puzzle.clues())))
    solved = set()
    for clue in steps:
        assert clue in puzzle.available(solved)
        solved.add(clue.index)
    text = puzzle.render(solved)
    assert "[" not in text and "]" not in text
    assert text == puzzle.solved_text
    assert puzzle.available(solved) == []


def test_render_progressively(puzzle):
    """Each step replaces one bracketed clue with its answer."""
    solved = []
    previous = puzzle.render()
    assert previous == puzzle.initialPuzzle
    for clue in puzzle.steps():
        solved.append(clue.text)  # texts, as saved games list them
        current = puzzle.render(solved)
        assert current == previous.replace(f"[{clue.text}]", clue.answer, 1)
        previous = current


def test_caption(puzzle):
    assert puzzle.caption_matches == (puzzle.puzzleDate not in CAPTION_MISMATCHES)


def test_caption_mismatches_are_in_the_fixtures():
    assert CAPTION_MISMATCHES <= {p["puzzleDate"] for p in PUZZLES}


def test_known_puzzle():
    puzzle = BracketCityPuzzle(**bracket_city_puzzle("2026-10-08"))
    assert puzzle.solved_text == puzzle.puzzleSolution == "Raytheon patents the microwave"
    assert puzzle.depth == 10
    leaves = [c.text for c in puzzle.available()]
    assert leaves == ["damage to stockings 🏃‍♀️", "compass RIGHT"]
    first = puzzle.clues()[0]
    assert first.text == "🩻 X-➡️ ___ ⬅️ Romano 🤷‍♂️" and first.answer == "Ray" and first.parent is None
    assert puzzle.steps()[-1] == first
    assert puzzle.render([first], mark=lambda a: f"<{a}>").startswith("<Ray>theon")


def test_known_caption_mismatch():
    puzzle = BracketCityPuzzle(**bracket_city_puzzle("2025-01-13"))
    assert not puzzle.caption_matches
    assert puzzle.solved_text != puzzle.puzzleSolution


def test_render_and_available_semantics():
    tree = Tree("Go [to the [big] apple] now [b]", {"big": "large", "to the large apple": "NYC", "b": "B"})
    outer, big, b = tree.clues
    assert (outer.index, outer.children, outer.depth, outer.parent) == (0, (1,), 1, None)
    assert (outer.text, outer.raw, outer.answer) == ("to the large apple", "to the [big] apple", "NYC")
    assert (big.index, big.depth, big.parent, big.leaf) == (1, 2, 0, True)
    assert (b.index, b.depth, b.text) == (2, 1, "b")
    assert [c.text for c in tree.available()] == ["big", "b"]
    # An outer clue can't be solved before the clues inside it.
    assert tree.render([0]) == "Go NYC now [b]"
    assert [c.text for c in tree.available([1])] == ["to the large apple", "b"]
    assert tree.render([1]) == "Go [to the large apple] now [b]"
    assert tree.render(["b", "unknown clue"]) == "Go [to the [big] apple] now B"
    assert [c.index for c in tree.steps()] == [1, 2, 0]
    assert tree.solved_text == "Go NYC now B"


def test_answers_found_ignoring_case_and_spaces():
    tree = Tree("[Big  ]!", {"big": "large"})
    assert tree.solved_text == "large!"


@pytest.mark.parametrize("initial,message", [
    ("a [b", r"unmatched \["),
    ("a ]b", r"unmatched \]"),
    ("[a [b]", r"unmatched \["),
    ("[a] b]", r"unmatched \]"),
])
def test_unmatched_brackets(initial, message):
    with pytest.raises(AtlanticGamesParseError, match=message):
        Tree(initial, {"a": "x", "b": "y"})


def test_missing_answer():
    with pytest.raises(AtlanticGamesParseError, match="no answer for the clue 'c'"):
        Tree("[c]", {"a": "x"})


def test_no_clues():
    tree = Tree("Nothing to solve", {})
    assert tree.clues == () and tree.steps() == [] and tree.solved_text == "Nothing to solve"
    assert BracketCityPuzzle(puzzleDate="2025-01-01", initialPuzzle="x", puzzleSolution="x", solutions={}).depth == 0
