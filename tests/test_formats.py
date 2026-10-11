"""Crossword export tests.

Uses real Amuse Labs puzzle JSON from tests/fixtures/crosswords and a small
made-up puzzle. The .puz output is checked with puzpy, the .ipuz output with
the ipuz package and the .xml output with Crossword Compiler's schema.
"""
import copy
import json
import pathlib
import xml.etree.ElementTree as ET

import ipuz
import puz
import pytest
import xmlschema

from atlgames import AtlanticGamesExportError
from atlgames.formats import FORMATS
from atlgames.formats import export
from atlgames.formats import export_problems
from atlgames.formats import fidelity
from atlgames.formats import to_ipuz
from atlgames.formats import to_puz
from atlgames.formats import to_xml
from atlgames.models import CrosswordPuzzle

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "crosswords"
NS = {"x": "http://crossword.info/xml/rectangular-puzzle"}

# A B C       1 2 .
# D # E   ->  . # .    (B is circled, G is shaded, the last square is a rebus)
# F G HH      3 . .
PUZZLE = {
    "id": "atlantic_20250612",
    "title": "Thursday, June 12, 2025",
    "author": "Ann Author; edited by Ed Editor",
    "copyright": "© Atlantic",
    "description": "A <b>note</b> about the puzzle.",
    "w": 3,
    "h": 3,
    "publishTime": 1749722400000,  # 2025-06-12 06:00 in New York
    "box": [["A", "D", "F"], ["B", "\u0000", "G"], ["C", "E", "HH"]],
    "clueNums": [["1", None, "3"], ["2", None, None], [None, None, None]],
    "cellInfos": [{"x": 1, "y": 0, "isCircled": True}, {"x": 1, "y": 2, "bgColor": "#abcdef"}],
    "placedWords": [
        {"originalTerm": "ABC", "nBoxes": 3, "x": 0, "y": 0, "acrossNotDown": True, "clueNum": "1",
         "clue": {"clue": "First “row”"}},
        {"originalTerm": "FGHH", "nBoxes": 3, "x": 0, "y": 2, "acrossNotDown": True, "clueNum": "3",
         "clue": {"clue": "Last row…"}},
        {"originalTerm": "ADF", "nBoxes": 3, "x": 0, "y": 0, "acrossNotDown": False, "clueNum": "1",
         "clue": {"clue": "Left <i>column</i>"}},
        {"originalTerm": "CEHH", "nBoxes": 3, "x": 2, "y": 0, "acrossNotDown": False, "clueNum": "2",
         "clue": {"clue": "Right – column"}},
    ],
}


def puzzle(**changes) -> CrosswordPuzzle:
    """Return the made-up puzzle, with dotted-path changes such as placedWords.0.clueNum."""
    data = copy.deepcopy(PUZZLE)
    for path, value in changes.items():
        target = data
        *parents, last = path.split(".")
        for key in parents:
            target = target[int(key)] if key.isdigit() else target[key]
        target[int(last) if last.isdigit() else last] = value
    return CrosswordPuzzle(**data)


def fixture(name: str) -> CrosswordPuzzle:
    return CrosswordPuzzle(**json.loads((FIXTURES / name).read_text()))


@pytest.fixture(scope="module")
def schema():
    # The published schema leaves out elementFormDefault, and one of its
    # rich-text elements doesn't build, so load it leniently.
    text = (FIXTURES / "rectangular-puzzle.xsd").read_text()
    return xmlschema.XMLSchema(text.replace("<schema ", '<schema elementFormDefault="qualified" ', 1),
                               validation="lax")


def test_puz_is_valid_and_complete():
    data = to_puz(puzzle())
    p = puz.load(data)

    assert p.tobytes() == data  # puzpy recomputes every checksum
    assert (p.width, p.height) == (3, 3)
    assert p.solution == "ABCD.EFGH"
    assert p.fill == "----.----"
    assert p.title == "The Atlantic Crossword: Thursday, June 12, 2025"
    assert (p.author, p.copyright) == ("Ann Author / Edited by Ed Editor", "© Atlantic")
    assert p.notes == "A note about the puzzle."
    numbering = p.clue_numbering()
    assert [(c["num"], c["clue"]) for c in numbering.across] == [(1, 'First "row"'), (3, "Last row...")]
    assert [(c["num"], c["clue"]) for c in numbering.down] == [(1, "Left column"), (2, "Right - column")]
    assert p.rebus().get_rebus_solution(8) == "HH"
    assert p.markup().get_markup_squares() == [1, 7]


def test_ipuz_is_valid_and_complete():
    document = to_ipuz(puzzle())
    ipuz.read(json.dumps(document))

    assert document["puzzle"] == [[1, {"cell": 0, "style": {"shapebg": "circle"}}, 2],
                                  [0, "#", 0],
                                  [3, {"cell": 0, "style": {"color": "ABCDEF"}}, 0]]
    assert document["solution"] == [["A", "B", "C"], ["D", "#", "E"], ["F", "G", "HH"]]
    assert document["clues"]["Down"] == [[1, "Left column"], [2, "Right – column"]]
    assert document["clues"]["Across"] == [[1, "First “row”"], [3, "Last row…"]]
    assert (document["author"], document["editor"]) == ("Ann Author", "Ed Editor")
    assert document["date"] == "06/12/2025"
    assert document["publisher"] == "The Atlantic"
    assert "saved" not in document


def test_xml_is_complete(schema):
    text = to_xml(puzzle(), title="My title")
    schema.validate(text)
    root = ET.fromstring(text)

    assert root.find("x:metadata/x:title", NS).text == "My title"
    assert root.find("x:metadata/x:identifier", NS).text == "urn:amuselabs:atlantic:atlantic_20250612"
    cells = root.findall("x:crossword/x:grid/x:cell", NS)
    assert len(cells) == 9
    assert cells[4].get("type") == "block"
    assert cells[1].get("background-shape") == "circle"
    assert cells[7].get("background-color") == "#ABCDEF"
    assert cells[8].get("solution") == "HH"
    words = root.findall("x:crossword/x:word", NS)
    assert [(w.get("x"), w.get("y")) for w in words] == [("1-3", "1"), ("1-3", "3"), ("1", "1-3"), ("3", "1-3")]
    clues = root.findall("x:crossword/x:clues/x:clue", NS)
    assert [(c.get("word"), c.get("number"), c.text) for c in clues][0] == ("1", "1", "First “row”")


@pytest.mark.parametrize("name,size,clues,title", [
    ("daily_20261010.json", (10, 10), 28, "The Atlantic Crossword: Saturday, October 10, 2026"),
    ("inferno_20260517.json", (7, 25), 57, "Caleb's Inferno: June 2026"),
    ("daily_20180924.json", (5, 5), 10, "The Atlantic Crossword: Monday, September 24, 2018"),
])
def test_real_puzzles_round_trip(schema, name, size, clues, title):
    p = fixture(name)
    grid = p.grid()
    solution = "".join("." if letter is None else letter[0] for row in grid for letter in row)

    for fmt in FORMATS:
        assert export_problems(p, fmt) == []

    data = to_puz(p)
    q = puz.load(data)
    assert q.tobytes() == data
    assert (q.width, q.height) == size
    assert q.title == title
    assert q.solution == solution
    assert len(q.clues) == clues
    numbering = q.clue_numbering()
    entries = {e.id: e for e in p.entries()}
    for direction, items in (("Across", numbering.across), ("Down", numbering.down)):
        for item in items:
            entry = entries[f"{item['num']}-{direction}"]
            assert item["cell"] == entry.cells[0]
            assert item["len"] == len(entry.cells)

    document = ipuz.read(export(p, "ipuz").decode())
    assert document["dimensions"] == {"width": size[0], "height": size[1]}
    assert len(document["clues"]["Across"]) + len(document["clues"]["Down"]) == clues
    assert not any("<" in text for _, text in document["clues"]["Across"] + document["clues"]["Down"])

    xml = export(p, "xml").decode()
    schema.validate(xml)
    assert len(ET.fromstring(xml).findall("x:crossword/x:clues/x:clue", NS)) == clues


def test_old_puzzles_zero_labels_arent_numbers():
    p = fixture("daily_20180924.json")
    document = to_ipuz(p)
    assert document["puzzle"][1] == [5, 0, 0, 0, 6]
    assert [s.label for s in p.squares()][5:10] == ["5", None, None, None, "6"]


@pytest.mark.parametrize("changes,reason", [
    ({"clueNums.0.0": "A"}, "squares labeled with text (A)"),
    ({"placedWords.0.clueNum": None}, "clues without numbers"),
    ({"placedWords.0.nBoxes": 4}, "1-Across runs outside the grid"),
    ({"placedWords.2.x": 1}, "1-Down runs over a black square"),
    ({"box.2": ["C", "E"]}, "a grid that isn't rectangular"),
])
def test_gimmicks_cant_be_exported(changes, reason):
    p = puzzle(**changes)
    for fmt in FORMATS:
        with pytest.raises(AtlanticGamesExportError) as info:
            export(p, fmt)
        assert reason in info.value.reasons
        assert export_problems(p, fmt) == info.value.reasons


def test_puz_needs_standard_numbering():
    p = puzzle(**{"placedWords.3.clueNum": "4"})
    assert export_problems(p, "puz") == ["numbering or entries that don't follow standard crossword rules"]
    assert export_problems(p, "ipuz") == []


def test_puz_rejects_text_it_cant_store():
    p = puzzle(**{"placedWords.0.clue.clue": "I ♥ NY"})
    assert export_problems(p, "puz") == ["clues with characters .puz can't store (♥)"]
    assert export_problems(p, "ipuz") == []


def test_unknown_format():
    with pytest.raises(ValueError):
        export(puzzle(), "pdf")


def test_titles():
    assert to_ipuz(puzzle(id="inferno_20250612"))["title"] == "Caleb's Inferno: Thursday, June 12, 2025"
    assert to_ipuz(puzzle(series="atlantic-inferno"))["title"].startswith("Caleb's Inferno")
    assert to_ipuz(puzzle(title=""))["title"] == "The Atlantic Crossword, 2025-06-12"
    assert to_ipuz(puzzle(), title="Mine")["title"] == "Mine"


def test_fidelity():
    assert fidelity(puzzle(), "ipuz") == ["clue formatting such as italics is dropped (1 clue)"]
    puz_notes = fidelity(puzzle(), "puz")
    assert "1 shaded square is shown as a circle" in puz_notes
    assert "typographic punctuation is converted to plain text (– “ ” …)" in puz_notes
    assert fidelity(puzzle(**{"placedWords.2.clue.clue": "Left column"}), "xml") == []
    with pytest.raises(AtlanticGamesExportError):
        fidelity(puzzle(**{"clueNums.0.0": "A"}), "ipuz")
