"""Amuse Labs page parsing and puzzle decoding, on captured pages."""
import base64
import json

import pytest

from atlgames import AtlanticGamesParseError
from atlgames import amuse
from tests.support import b64json
from tests.support import crossword_page
from tests.support import crossword_params
from tests.support import text


@pytest.mark.parametrize("name,size,words", [
    ("atlantic_20261010", (10, 10), 28),
    ("2fbb3c8f", (5, 5), 10),  # 2018, a hex ID
    ("inferno_20260517", (7, 25), 57),
])
def test_decode_rawc(name, size, words):
    params = crossword_params(name)
    data = amuse.decode_rawc(params["rawc"])
    assert data["id"] == params["puzzleId"] == name
    assert (data["w"], data["h"]) == size
    assert len(data["placedWords"]) == words


def test_rawc_is_scrambled():
    rawc = crossword_params("atlantic_20261010")["rawc"]
    with pytest.raises(ValueError):
        json.loads(base64.b64decode(rawc + "=" * (-len(rawc) % 4)))
    assert amuse.unscramble(rawc) != rawc
    assert len(amuse.unscramble(rawc)) >= len(rawc)


def test_unscramble_reverses_runs():
    # Reverse runs of 3 and 2 characters, then skip 2.
    passes = ((0, 2, (3, 2)),)
    assert amuse.unscramble("abcdefghijkl", passes) == "cbaed" + "fg" + "jih" + "lk"
    # A run can reach one past the end, as in Amuse Labs' JS.
    assert amuse.unscramble("abcd", ((0, 10, (3, 3)),)) == "cbad"
    assert amuse.unscramble("", passes) == ""


def test_plain_base64_fallback():
    """A puzzle that isn't scrambled still decodes."""
    puzzle = {"id": "plain", "w": 1, "h": 1}
    assert amuse.decode_rawc(b64json(puzzle)) == puzzle


@pytest.mark.parametrize("rawc", ["not base64 at all!", b64json([1, 2, 3]), ""])
def test_decode_rawc_errors(rawc):
    with pytest.raises(AtlanticGamesParseError, match="changed its encoding"):
        amuse.decode_rawc(rawc)


def test_decode_rawc_with_wrong_passes_fails():
    rawc = crossword_params("atlantic_20261010")["rawc"]
    with pytest.raises(AtlanticGamesParseError):
        amuse.decode_rawc(rawc, ((0, 40, (9, 7)),))


def test_passes_from_js():
    """The constants read from Amuse Labs' unscramble function match the built-in ones."""
    assert amuse.passes_from_js(text("crossword/c-min-Vf.js")) == amuse.SCRAMBLE_PASSES


def test_passes_from_js_renamed_function():
    """Minifiers rename functions; the function is also found by its shape."""
    js = text("crossword/c-min-Vf.js").replace("function Vf(", "function Qx(")
    assert amuse.passes_from_js(js) == amuse.SCRAMBLE_PASSES


def test_passes_from_js_new_constants():
    js = text("crossword/c-min-Vf.js")
    changed = js.replace("c=14+s<t.length?15", "c=12+s<t.length?13").replace("n+=52", "n+=50")
    passes = amuse.passes_from_js(changed)
    assert passes[0] == (0, 50, (13, 10, 11))
    assert passes[1] == amuse.SCRAMBLE_PASSES[1]


@pytest.mark.parametrize("js,message", [
    ("function other(t){return t}", "find Amuse Labs' unscramble function"),
    ('function Vf(t){var e,i=t.split("");return i.join("")}', "read Amuse Labs' unscramble constants"),
])
def test_passes_from_js_errors(js, message):
    with pytest.raises(AtlanticGamesParseError, match=message):
        amuse.passes_from_js(js)


def test_page_params():
    params = amuse.page_params(text("crossword/atlantic_20261010.html"))
    assert params["puzzleId"] == "atlantic_20261010"
    assert params["resourceVersionDir"] == "b67da0d"
    assert amuse.decode_field(params, "rawp")["playState"] == 0


def test_error_page():
    html = text("crossword/error.html")
    assert amuse.is_error_page(html)
    assert not amuse.is_error_page(text("crossword/atlantic_20261010.html"))
    assert "rawc" not in amuse.page_params(html)


@pytest.mark.parametrize("html,message", [
    ("<html><head><title>Oops</title></head><body></body></html>", r"no puzzle data \(Oops\)"),
    ("<html><body>nothing</body></html>", r"no puzzle data \(no title\)"),
    ('<html><script id="params">{not json</script></html>', "isn't valid JSON"),
])
def test_page_params_errors(html, message):
    with pytest.raises(AtlanticGamesParseError, match=message):
        amuse.page_params(html)


def test_page_params_attribute_order():
    html = "<script id='params' type='application/json'>{\"a\": 1}</script>"
    assert amuse.page_params(html) == {"a": 1}


def test_decode_field():
    params = {"rawp": b64json({"playState": 2}), "bad": "%%%", "empty": "", "list": b64json([1])}
    assert amuse.decode_field(params, "rawp") == {"playState": 2}
    assert amuse.decode_field(params, "bad") is None
    assert amuse.decode_field(params, "empty") is None
    assert amuse.decode_field(params, "missing") is None
    assert amuse.decode_field(params, "list") == [1]


def test_load_token():
    token = amuse.load_token(text("crossword/date_picker.html"))
    assert token.count(".") == 2


def test_load_token_from_puzzle_page_spelling():
    html = crossword_page({"rawSps": b64json({"loadToken": "tok"})})
    assert amuse.load_token(html) == "tok"


@pytest.mark.parametrize("params", [{"rawsps": b64json({"set": "atlantic"})}, {}])
def test_load_token_missing(params):
    with pytest.raises(AtlanticGamesParseError, match="no load token"):
        amuse.load_token(crossword_page(params))
