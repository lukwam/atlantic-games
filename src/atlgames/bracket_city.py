"""Bracket City puzzle structure.

A Bracket City puzzle is a sentence with clues in square brackets, nested
inside each other. You solve a clue once every clue inside it is solved, and
its answer replaces it in the text around it. `solutions` maps each clue's
*resolved* text (with its inner clues already replaced by their answers) to
its answer, so the whole puzzle can be solved by resolving the innermost
clues first.

The puzzle's `puzzleSolution` is an editorial caption and differs from the
resolved text in about 1 in 30 puzzles (spacing, wording, typos), so use
`BracketCityPuzzle.solved_text` for what the game actually shows.
"""
from dataclasses import dataclass
from typing import Iterable
from typing import Mapping

from atlgames.exceptions import AtlanticGamesParseError


@dataclass(frozen=True)
class Clue:
    """One clue in a Bracket City puzzle."""

    #: Position in the puzzle, in the order the clues' brackets open.
    index: int
    #: The clue as the game shows it once every clue inside it is solved.
    #: This is its key in the puzzle's `solutions`, and what saved games
    #: list in `solvedExpressions`.
    text: str
    answer: str
    #: The clue as written, with its inner clues still in brackets.
    raw: str
    #: 1 for clues in the sentence itself, 2 for clues inside those, ...
    depth: int
    #: Index of the clue this one is inside, or None.
    parent: int | None
    #: Indexes of the clues directly inside this one.
    children: tuple[int, ...]

    @property
    def leaf(self) -> bool:
        """True if the clue has no clues inside it, so it can be solved first."""
        return not self.children


@dataclass
class _Node:
    index: int
    parent: int | None
    depth: int
    # literal strings and child indexes, in order
    parts: list


def _parse(initial: str) -> tuple[list, list[_Node]]:
    """Return the top-level parts and every clue node."""
    root: list = []
    nodes: list[_Node] = []
    stack: list[_Node] = []
    buffer = []

    def flush(target):
        if buffer:
            target.append("".join(buffer))
            buffer.clear()

    for char in initial:
        target = stack[-1].parts if stack else root
        if char == "[":
            flush(target)
            node = _Node(len(nodes), stack[-1].index if stack else None, len(stack) + 1, [])
            nodes.append(node)
            target.append(node.index)
            stack.append(node)
        elif char == "]":
            if not stack:
                raise AtlanticGamesParseError("Bracket City puzzle has an unmatched ]")
            flush(target)
            stack.pop()
        else:
            buffer.append(char)
    if stack:
        raise AtlanticGamesParseError("Bracket City puzzle has an unmatched [")
    flush(root)
    return root, nodes


def _lookup(solutions: Mapping[str, str], text: str) -> str:
    if text in solutions:
        return solutions[text]
    folded = {key.strip().casefold(): value for key, value in solutions.items()}
    answer = folded.get(text.strip().casefold())
    if answer is None:
        raise AtlanticGamesParseError(f"Bracket City puzzle has no answer for the clue {text!r}")
    return answer


class Tree:
    """A Bracket City puzzle's clues and how they nest."""

    def __init__(self, initial: str, solutions: Mapping[str, str]):
        self.initial = initial
        self._root, nodes = _parse(initial)
        texts: dict[int, str] = {}
        answers: dict[int, str] = {}
        raws: dict[int, str] = {}

        def raw(node: _Node) -> str:
            return "".join(p if isinstance(p, str) else f"[{raw(nodes[p])}]" for p in node.parts)

        # Children always come after their parent, so resolve in reverse.
        for node in reversed(nodes):
            text = "".join(p if isinstance(p, str) else answers[p] for p in node.parts)
            texts[node.index] = text
            answers[node.index] = _lookup(solutions, text)
            raws[node.index] = raw(node)
        self.clues: tuple[Clue, ...] = tuple(
            Clue(index=n.index, text=texts[n.index], answer=answers[n.index], raw=raws[n.index],
                 depth=n.depth, parent=n.parent,
                 children=tuple(p for p in n.parts if not isinstance(p, str)))
            for n in nodes
        )
        self._nodes = nodes

    def _indexes(self, solved: Iterable[int | str | Clue]) -> set[int]:
        by_text = {clue.text: clue.index for clue in self.clues}
        result = set()
        for item in solved:
            if isinstance(item, Clue):
                result.add(item.index)
            elif isinstance(item, int):
                result.add(item)
            elif item in by_text:
                result.add(by_text[item])
        return result

    def render(self, solved: Iterable[int | str | Clue] = (), mark=None) -> str:
        """Return the puzzle text with the solved clues replaced by their answers.

        `solved` holds clues, their indexes or their texts (as in a saved
        game's `solvedExpressions`). `mark`, if given, is called with each
        solved clue's answer, e.g. to highlight it.
        """
        done = self._indexes(solved)

        def part(p) -> str:
            if isinstance(p, str):
                return p
            if p in done:
                answer = self.clues[p].answer
                return mark(answer) if mark else answer
            return "[" + "".join(part(q) for q in self._nodes[p].parts) + "]"

        return "".join(part(p) for p in self._root)

    def available(self, solved: Iterable[int | str | Clue] = ()) -> list[Clue]:
        """Return the unsolved clues that can be solved now: every clue inside
        them is solved."""
        done = self._indexes(solved)
        return [clue for clue in self.clues
                if clue.index not in done and all(c in done for c in clue.children)]

    def steps(self) -> list[Clue]:
        """Return the clues in an order that solves the puzzle: innermost
        first, left to right."""
        order, done = [], set()
        while len(done) < len(self.clues):
            ready = self.available(done)
            order.extend(ready)
            done.update(clue.index for clue in ready)
        return order

    @property
    def solved_text(self) -> str:
        """The puzzle's text with every clue solved."""
        return self.render(range(len(self.clues)))
