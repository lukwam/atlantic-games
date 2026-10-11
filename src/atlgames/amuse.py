"""Amuse Labs PuzzleMe pages: the Atlantic's crosswords.

The Atlantic's Crossword and Caleb's Inferno are hosted by Amuse Labs on
`cdn3.amuselabs.com/atlantic`. A puzzle page carries its data in a
`<script id="params">` JSON block: `rawc` is the puzzle as base64 JSON,
lightly scrambled by reversing fixed-length runs of characters (the `Vf`
function in Amuse Labs' `c-min.js`), and `rawp` is the play saved for the
page's `uid`.

The run lengths live in Amuse Labs' versioned JavaScript, so they can change
when Amuse Labs deploys. `decode_rawc` tries the known lengths, then plain
base64; the client re-reads the lengths from the current `c-min.js` when
both fail.
"""
import base64
import json
import re

from atlgames.exceptions import AtlanticGamesParseError

AMUSE_URL = "https://cdn3.amuselabs.com/atlantic"

#: (start, step, run lengths) for each pass of Amuse Labs' unscramble.
#: Taken from c-min.js in resource version b67da0d (2026-10).
SCRAMBLE_PASSES: tuple[tuple[int, int, tuple[int, ...]], ...] = (
    (0, 52, (15, 10, 11)),
    (36, 36, (17, 14, 4, 17)),
)

PARAMS = re.compile(r'<script[^>]*\bid=["\']?params["\']?[^>]*>(.*?)</script>', re.S)
TITLE = re.compile(r"<title>(.*?)</title>", re.S)


def _reverse_runs(chars: list[str], start: int, length: int, size: int) -> int:
    """Reverse the next run in place, as Amuse Labs' JS does (including its
    run that can reach one past the end), and return where the run ends."""
    run = size if (size - 1) + start < length else length - start + 1
    left, right = start, start + run - 1
    while len(chars) <= right:
        chars.append("")
    while left < right:
        chars[left], chars[right] = chars[right], chars[left]
        left += 1
        right -= 1
    return start + run


def unscramble(text: str, passes=SCRAMBLE_PASSES) -> str:
    """Undo Amuse Labs' character scramble."""
    chars = list(text)
    length = len(text)
    for start, step, sizes in passes:
        n = start
        while n < length:
            s = n
            for size in sizes:
                s = _reverse_runs(chars, s, length, size)
            n = s + step
    return "".join(chars)


def _b64json(text: str):
    return json.loads(base64.b64decode(text + "=" * (-len(text) % 4)).decode("utf-8"))


def decode_rawc(rawc: str, passes=SCRAMBLE_PASSES) -> dict:
    """Return the puzzle JSON from a page's `rawc`.

    Raises AtlanticGamesParseError if it can't be decoded with these passes
    or as plain base64.
    """
    for candidate in (unscramble(rawc, passes), rawc):
        try:
            data = _b64json(candidate)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            return data
    raise AtlanticGamesParseError(
        "Couldn't decode the Amuse Labs puzzle; Amuse Labs may have changed its encoding")


_PASS = re.compile(r"for\((?:var )?n=(\d+);n<t\.length;n\+=(\d+)\)\{(.*?)\}?(?=\(e=\[\]\)|for\((?:var )?n=|$)",
                   re.S)
_RUN = re.compile(r"c=(\d+)\+s<t\.length\?(\d+):")


def passes_from_js(js: str) -> tuple[tuple[int, int, tuple[int, ...]], ...]:
    """Read the scramble passes from Amuse Labs' c-min.js.

    Raises AtlanticGamesParseError if the unscramble function isn't found.
    """
    start = js.find("function Vf(t)")
    if start < 0:
        match = re.search(r"function \w+\(t\)\{var e,i=t\.split\(\"\"\);\(e=\[\]\)\.push", js)
        start = match.start() if match else -1
    if start < 0:
        raise AtlanticGamesParseError("Couldn't find Amuse Labs' unscramble function")
    body = js[start:start + 4000]
    body = body[:body.find("return i.join")] if "return i.join" in body else body
    passes = []
    for match in _PASS.finditer(body):
        sizes = tuple(int(b) for a, b in _RUN.findall(match.group(3)) if int(b) == int(a) + 1)
        if sizes:
            passes.append((int(match.group(1)), int(match.group(2)), sizes))
    if not passes:
        raise AtlanticGamesParseError("Couldn't read Amuse Labs' unscramble constants")
    return tuple(passes)


def page_params(html: str) -> dict:
    """Return a PuzzleMe page's params, or raise.

    PuzzleMe answers unknown or unpublished puzzles with HTTP 200 and an
    error page, so that's raised as AtlanticGamesParseError with the page's
    title here and turned into a not found error by the client.
    """
    match = PARAMS.search(html)
    if not match:
        title = TITLE.search(html)
        raise AtlanticGamesParseError(
            f"Amuse Labs returned no puzzle data ({title.group(1).strip() if title else 'no title'})")
    try:
        return json.loads(match.group(1))
    except ValueError:
        raise AtlanticGamesParseError("Amuse Labs' puzzle data isn't valid JSON") from None


def is_error_page(html: str) -> bool:
    title = TITLE.search(html)
    return bool(title and "PuzzleMe Error" in title.group(1))


def decode_field(params: dict, name: str):
    """Return a plain base64 JSON params field (rawp, rawsps, rawd, ...), or None."""
    value = params.get(name)
    if not value:
        return None
    try:
        return _b64json(value)
    except (ValueError, UnicodeDecodeError):
        return None


def load_token(date_picker_html: str) -> str:
    """Return the anonymous loadToken from a date picker page."""
    params = page_params(date_picker_html)
    sps = decode_field(params, "rawsps") or decode_field(params, "rawSps") or {}
    token = sps.get("loadToken")
    if not token:
        raise AtlanticGamesParseError("Amuse Labs' date picker had no load token")
    return token
