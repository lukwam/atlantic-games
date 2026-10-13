"""atlg command line tests.

The Atlantic client is replaced with a mock, so these run offline.
"""
import base64
import datetime
import json
import stat
import sys
import time
from pathlib import Path
from unittest import mock

import httpx
import pytest
from typer.testing import CliRunner

from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesNotFoundError
from atlgames import AtlanticGamesRateLimitError
from atlgames.cli import app as cli_main
from atlgames.cli import dates
from atlgames.cli import output
from atlgames.cli.state import State
from atlgames.models import BracketCityGame
from atlgames.models import BracketCityPuzzle
from atlgames.models import CrosswordListing
from atlgames.models import CrosswordPlay
from atlgames.models import CrosswordPuzzle
from atlgames.models import RabbitholeGame
from atlgames.models import RabbitholePuzzle
from atlgames.models import StacksPuzzle
from atlgames.models import TriviaArticle

runner = CliRunner()

BRACKET = BracketCityPuzzle(
    puzzleDate="2026-10-04",
    initialPuzzle="The [opposite of [color of snow]] cat sat on the [floor covering]",
    puzzleSolution="The black cat sat on the mat",
    solutions={"color of snow": "white", "opposite of white": "black", "floor covering": "mat"},
    completionText="Cats were domesticated about 10,000 years ago.",
    completionURL="https://example.com/cats",
    author="Ben Gross",
)
# A 2x2 crossword: AB / CD. Amuse Labs stores the grid column by column.
CROSSWORD = CrosswordPuzzle(
    id="atlantic_20261004", title="Sunday, October 4, 2026", author="Ann Author; edited by Ed Editor",
    w=2, h=2, box=[["A", "C"], ["B", "D"]], clueNums=[["1", "3"], ["2", None]],
    placedWords=[
        {"originalTerm": "AB", "nBoxes": 2, "x": 0, "y": 0, "acrossNotDown": True, "clueNum": "1",
         "clue": {"clue": "<i>First</i> pair"}},
        {"originalTerm": "CD", "nBoxes": 2, "x": 0, "y": 1, "acrossNotDown": True, "clueNum": "3",
         "clue": {"clue": "Second pair"}},
        {"originalTerm": "AC", "nBoxes": 2, "x": 0, "y": 0, "acrossNotDown": False, "clueNum": "1",
         "clue": {"clue": "Left side"}},
        {"originalTerm": "BD", "nBoxes": 2, "x": 1, "y": 0, "acrossNotDown": False, "clueNum": "2",
         "clue": {"clue": "Right side"}},
    ],
    publishTime=1791086400000, series="atlantic",
)
RABBITHOLE = RabbitholePuzzle(
    id="53", publishedAt="2026-10-02T04:00:00Z", byline="Drew Goins",
    recirculationBlurb="All about <em>owls</em>.",
    article={"id": "BlogArticle:1", "title": "Owls", "url": "https://example.com/owls"},
    questions=[
        {"id": "1", "questionText": "What bird hoots?", "canonicalAnswer": "Owl", "hintText": "Nocturnal",
         "choices": ["Duck", "Crow"]},
        {"id": "2", "questionText": "An <em>owl</em> is a symbol of what goddess?", "canonicalAnswer": "Athena",
         "hintText": "Greek", "choices": ["Hera", "Gaia"]},
    ],
)
TRIVIA = TriviaArticle(
    id="BlogArticle:688280", title="<em>Atlantic</em> Trivia: Last Call!", url="https://example.com/688280/",
    datePublished="2026-08-14T10:00:00Z",
    questions=[{"id": "q1", "questionText": "What mammal is a trash panda?", "canonicalAnswer": "Raccoon",
                "topicText": "Critters", "subtext": "<p>They wash food.</p>"}],
)
STACKS = StacksPuzzle(date="2026-08-24", id=433, wordStrings=["ab", "cd"], blackPos="ef", solution=[0, 10])


def bracket_game(day: str, **state) -> BracketCityGame:
    return BracketCityGame(gameKey=f"bracket-city#{day}#v1", gameSlug="bracket-city", gameDate=day, gameId="v1",
                           progress="complete" if state.get("isComplete") else "inProgress", gameState=state)


def rabbithole_game(puzzle_id: str, day: str, results: list[str], score: int) -> RabbitholeGame:
    return RabbitholeGame(gameKey=f"rabbithole#{day}#{puzzle_id}", gameSlug="rabbithole", gameDate=day,
                          gameId=puzzle_id, progress="complete",
                          gameState={"questionResults": results, "score": score, "status": "complete"})


def jwt(claims: dict) -> str:
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256'})}.{part(claims)}.signature"


TOKEN = jwt({"uuid": "user-1", "exp": time.time() + 86400})


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Use a temporary config directory and no cookies from the environment."""
    monkeypatch.setenv("ATLG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("ATLANTIC_COOKIES", raising=False)
    monkeypatch.delenv("ATLG_PROFILE", raising=False)
    monkeypatch.setattr(dates, "today", lambda: datetime.date(2026, 10, 4))
    output.default_format = None


@pytest.fixture
def client(monkeypatch):
    """Replace the CLI's Atlantic client with a mock."""
    fake = mock.Mock()
    monkeypatch.setattr(State, "client", lambda self: fake)
    return fake


def run(*args, **kwargs):
    return runner.invoke(cli_main.app, list(args), **kwargs)


def run_json(*args):
    result = run(*args, "-f", "json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@pytest.mark.parametrize("text,game,expected", [
    ("today", None, "2026-10-04"),
    ("yesterday", None, "2026-10-03"),
    ("friday", None, "2026-10-02"),
    ("2025-06-12", None, "2025-06-12"),
    ("first", "bracket-city", "2025-01-01"),
    ("last", "stacks", "2026-08-24"),
    ("last", "bracket-city", "2026-10-04"),
])
def test_parse_date(text, game, expected):
    assert dates.parse_date(text, game).isoformat() == expected


def test_parse_date_errors():
    with pytest.raises(ValueError):
        dates.parse_date("first")
    with pytest.raises(ValueError):
        dates.parse_date("someday")


def test_bracket_city_hides_the_answers_unless_asked(client):
    client.bracket_city.return_value = BRACKET

    hidden = run_json("bracket-city", "2026-10-04")
    shown = run_json("bracket-city", "2026-10-04", "--answers")

    assert hidden == {"date": "2026-10-04", "author": "Ben Gross", "puzzle": BRACKET.initialPuzzle,
                      "clue_count": 3, "depth": 2}
    assert shown["solution"] == "The black cat sat on the mat"
    assert shown["completion_url"] == "https://example.com/cats"
    assert [c["answer"] for c in shown["clues"]] == ["black", "white", "mat"]
    client.bracket_city.assert_called_with("2026-10-04")


def test_bracket_city_today_asks_for_the_latest(client):
    client.bracket_city.return_value = BRACKET
    result = run("bracket-city")
    assert result.exit_code == 0, result.output
    assert "opposite of" in result.stdout and "black" not in result.stdout
    client.bracket_city.assert_called_once_with(None)


def test_bracket_city_clues_dont_give_inner_answers_away(client):
    client.bracket_city.return_value = BRACKET
    data = run_json("bracket-city", "2026-10-04", "--clues")
    assert [(c["number"], c["clue"], c["parent"]) for c in data["clues"]] == [
        (1, "opposite of [#2]", None), (2, "color of snow", 1), (3, "floor covering", None)]
    assert "white" not in json.dumps(data) and "solution" not in data


def test_bracket_city_steps(client):
    client.bracket_city.return_value = BRACKET
    data = run_json("bracket-city", "2026-10-04", "--steps")
    assert [(s["clue"], s["answer"]) for s in data["steps"]] == [
        ("color of snow", "white"), ("floor covering", "mat"), ("opposite of white", "black")]


def test_value_format_and_root_format(client):
    client.bracket_city.return_value = BRACKET
    assert run("bracket-city", "2026-10-04", "-a", "-f", "value(solution,clue_count)").stdout == \
        "The black cat sat on the mat\t3\n"
    header = run("-f", "csv", "bracket-city", "2026-10-04").stdout.splitlines()[0]
    assert header == "date,author,puzzle,clue_count,depth"


def test_crossword_hides_the_answers_unless_asked(client):
    client.crossword.return_value = CROSSWORD

    hidden = run_json("crossword", "2026-10-04")
    shown = run_json("crossword", "2026-10-04", "-a")

    assert hidden["grid"] == ["..", ".."]
    assert hidden["clues"]["across"][0] == {"label": "1", "clue": "First pair", "length": 2}
    assert (hidden["constructor"], hidden["editor"]) == ("Ann Author", "Ed Editor")
    assert shown["grid"] == ["AB", "CD"]
    assert shown["clues"]["down"][1]["answer"] == "BD"
    client.crossword.assert_called_with("2026-10-04", series="daily")
    table = run("crossword", "2026-10-04").stdout
    assert "First pair" in table and "Ann Author" in table


def test_crossword_by_id_and_inferno(client):
    client.crossword.return_value = CROSSWORD
    run_json("crossword", "--id", "atlantic_20260101")
    client.crossword.assert_called_with(puzzle_id="atlantic_20260101", series="daily")

    client.crosswords.return_value = [CrosswordListing(puzzleId="inferno_20260517", series="atlantic-inferno")]
    run_json("crossword", "2026-06-01", "--series", "inferno")
    client.crosswords.assert_called_with("inferno", date_end="2026-06-01", limit=1)
    client.crossword.assert_called_with(puzzle_id="inferno_20260517", series="inferno")


def test_crossword_save(client, tmp_path):
    client.crossword.return_value = CROSSWORD
    path = tmp_path / "x.ipuz"
    result = run("crossword", "2026-10-04", "--save", str(path))
    assert result.exit_code == 0, result.output
    assert json.loads(path.read_text())["solution"] == [["A", "B"], ["C", "D"]]
    assert run("crossword", "--save", str(tmp_path / "x.pdf")).exit_code == 2


def test_rabbithole_shows_only_the_first_question(client):
    client.rabbithole.return_value = RABBITHOLE

    hidden = run_json("rabbithole")
    shown = run_json("rabbithole", "53", "--answers")

    assert [q["question"] for q in hidden["questions"]] == ["What bird hoots?"]
    assert "answer" not in hidden["questions"][0]
    assert "Athena" not in json.dumps(hidden) and "goddess" not in json.dumps(hidden)
    assert [q["answer"] for q in shown["questions"]] == ["Owl", "Athena"]
    assert shown["blurb"] == "All about owls."
    client.rabbithole.assert_called_with("53")


def test_rabbithole_by_date(client):
    client.rabbithole_puzzles.return_value = [RABBITHOLE]
    assert run_json("rabbithole", "friday")["id"] == "53"
    client.rabbithole_puzzles.assert_called_once_with("2026-10-02", "2026-10-02")

    client.rabbithole_puzzles.return_value = []
    assert run("rabbithole", "2026-10-03").exit_code == 1


def test_trivia_by_date_and_id(client):
    client.trivia_articles.return_value = [TRIVIA.model_copy(update={"questions": []})]
    client.trivia.return_value = TRIVIA

    data = run_json("trivia", "2026-08-14")
    assert data["title"] == "Atlantic Trivia: Last Call!"
    assert data["questions"] == [{"number": 1, "topic": "Critters", "question": "What mammal is a trash panda?"}]

    answered = run_json("trivia", "688280", "-a")
    assert answered["questions"][0]["answer"] == "Raccoon"
    assert answered["questions"][0]["explanation"] == "They wash food."
    client.trivia.assert_called_with("688280")


def test_stacks(client):
    client.stacks.return_value = STACKS
    hidden = run_json("stacks")
    shown = run_json("stacks", "2026-08-24", "-a")
    assert hidden == {"date": "2026-08-24", "id": 433, "title": "", "words": ["ab", "cd"], "base": "ef"}
    assert shown["drops"] == [{"word": "ab", "column": 1}, {"word": "cd", "column": 1}]
    assert shown["board"] == ["cd", "ab", "ef"]
    client.stacks.assert_called_with("2026-08-24")


def test_list_crossword_defaults_to_30(client):
    client.crosswords.return_value = [CrosswordListing(
        puzzleId="atlantic_20261004", title="Sunday", author="Ann Author; edited by Ed Editor",
        gridWidth=5, gridHeight=5, publicationTime=1791086400000)]
    rows = run_json("list", "crossword")
    assert rows == [{"date": "2026-10-04", "id": "atlantic_20261004", "title": "Sunday",
                     "author": "Ann Author", "size": "5x5"}]
    client.crosswords.assert_called_once_with("daily", None, None, 30)


def test_bad_format_and_date_are_usage_errors(client):
    assert run("bracket-city", "-f", "xml").exit_code == 2
    result = run("bracket-city", "someday")
    assert result.exit_code == 2 and "Invalid date" in result.output
    client.bracket_city.assert_not_called()


@pytest.mark.parametrize("error,message", [
    (AtlanticGamesNotFoundError("No Bracket City puzzle for 1900-01-01"), "No Bracket City puzzle"),
    (AtlanticGamesAuthenticationError("401"), "atlg auth login"),
    (AtlanticGamesRateLimitError("429", retry_after=30), "Try again in 30 seconds"),
    (httpx.ConnectError("offline"), "Request failed"),
])
def test_main_reports_errors(client, monkeypatch, capsys, error, message):
    client.bracket_city.side_effect = error
    monkeypatch.setattr(sys, "argv", ["atlg", "bracket-city", "1900-01-01"])
    with pytest.raises(SystemExit) as exit_info:
        cli_main.main()
    assert exit_info.value.code == 1
    assert message in capsys.readouterr().err


def test_errors_never_print_cookie_values(monkeypatch, capsys):
    secret = "TOPSECRETCOOKIEVALUE"
    monkeypatch.setenv("ATLANTIC_COOKIES", f"atljwt6={secret}")

    def boom(self, *args, **kwargs):
        raise ValueError(f"Invalid header value b'atljwt6={secret}'")

    monkeypatch.setattr("atlgames.client.AtlanticGamesClient.bracket_city", boom)
    monkeypatch.setattr(sys, "argv", ["atlg", "bracket-city", "2026-10-04"])
    with pytest.raises(SystemExit) as exit_info:
        cli_main.main()
    err = capsys.readouterr().err
    assert exit_info.value.code == 1
    assert secret not in err and "Traceback" not in err and "ValueError" in err


def test_auth_login_saves_only_the_atlantic_cookies(tmp_path):
    export = tmp_path / "cookies.json"
    export.write_text(json.dumps([{"name": "atljwt6", "value": TOKEN}, {"name": "atljwt", "value": "x.y.z"},
                                  {"name": "other", "value": "tracking"}]))
    with mock.patch("atlgames.cli.settings.AtlanticGamesClient") as client_class:
        client_class.return_value.game_states.return_value = []
        result = run("auth", "login", "--from-file", str(export))

    assert result.exit_code == 0, result.output
    assert "user-1" in result.stdout and TOKEN not in result.stdout
    client_class.return_value.game_states.assert_called_once_with([("bracket-city", "2026-10-04", "v1")])
    config = tmp_path / "config" / "config.ini"
    assert f"cookies = atljwt6={TOKEN}; atljwt=x.y.z" in config.read_text()
    assert "tracking" not in config.read_text()
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    listed = run("config", "list").stdout
    assert TOKEN not in listed and "atljwt6=…" in listed


def test_auth_login_prompt_and_rejected_cookies(tmp_path):
    with mock.patch("atlgames.cli.settings.AtlanticGamesClient") as client_class:
        client_class.return_value.game_states.side_effect = AtlanticGamesAuthenticationError("Bad request")
        result = run("auth", "login", input=TOKEN + "\n")

    assert result.exit_code == 1 and "rejected" in result.stdout
    assert not (tmp_path / "config" / "config.ini").exists()


def test_auth_login_refuses_expired_cookies(tmp_path):
    expired = jwt({"uuid": "user-1", "exp": 1000})
    result = run("auth", "login", "--no-verify", input=expired + "\n")
    assert result.exit_code == 1 and "expired" in result.stdout
    assert not (tmp_path / "config" / "config.ini").exists()


def test_auth_status(monkeypatch):
    assert run("auth", "status").exit_code == 1
    monkeypatch.setenv("ATLANTIC_COOKIES", f"atljwt6={TOKEN}")
    with mock.patch("atlgames.client.AtlanticGamesClient.game_states", return_value=[]):
        result = run("auth", "status", "-f", "json")
    data = json.loads(result.stdout)
    assert result.exit_code == 0
    assert (data["logged_in"], data["user_id"], data["cookies"]) == (True, "user-1", "ATLANTIC_COOKIES")
    assert TOKEN not in result.stdout


def test_cookie_precedence(monkeypatch):
    state = State()
    state.config.set("default", "cookies", "atljwt6=from-config")
    assert state.resolve_cookies() == ("atljwt6=from-config", "profile 'default'")
    monkeypatch.setenv("ATLANTIC_COOKIES", "atljwt6=from-env")
    assert state.resolve_cookies()[1] == "ATLANTIC_COOKIES"
    state.cookies = "atljwt6=from-flag"
    assert state.resolve_cookies()[1] == "--cookies"


def test_config_and_profiles():
    assert run("-p", "alice", "config", "set", "format", "json").exit_code == 0
    assert run("-p", "alice", "config", "get", "format").stdout == "json\n"
    assert run("config", "get", "format").exit_code == 1
    assert run("config", "profiles", "activate", "alice").exit_code == 0
    profiles = json.loads(run("config", "profiles", "list", "-f", "json").stdout)
    assert {"name": "alice", "active": True, "cookies": False} in profiles
    assert run("config", "profiles", "delete", "alice").exit_code == 0
    assert run("config", "set", "colour", "red").exit_code == 2


def test_profile_format_is_the_default(client):
    client.bracket_city.return_value = BRACKET
    run("config", "set", "format", "json")
    assert json.loads(run("bracket-city", "2026-10-04").stdout)["clue_count"] == 3


def test_history_bracket_city(client):
    client.bracket_city_dates.return_value = ["2026-09-01", "2026-10-03", "2026-10-04"]
    client.game_states.return_value = [bracket_game(
        "2026-10-04", isComplete=True, solvedExpressions=["a", "b"], totalKeystrokes=20, minimumKeystrokes=10,
        wrongGuesses=1, peekedClues=[1], solvedOnPubDate=True)]

    rows = run_json("history", "bracket-city")

    assert [(r["date"], r["status"]) for r in rows] == [("2026-10-04", "complete"), ("2026-10-03", "not played")]
    assert (rows[0]["efficiency"], rows[0]["peeks"], rows[0]["solved_on_the_day"]) == (0.5, 1, True)
    client.game_states.assert_called_once_with([("bracket-city", "2026-10-03", "v1"),
                                                ("bracket-city", "2026-10-04", "v1")])


def test_history_rabbithole(client):
    client.rabbithole_puzzles.return_value = [RABBITHOLE]
    client.game_states.return_value = [rabbithole_game("53", "2026-10-02",
                                                       ["correct_first_try", "correct_with_hint"], 5)]
    rows = run_json("history", "rabbithole", "--from", "2026-10-01")
    assert rows == [{"date": "2026-10-02", "id": "53", "status": "complete", "score": 5, "max_score": 6,
                     "results": ["correct_first_try", "correct_with_hint"]}]
    client.rabbithole_puzzles.assert_called_once_with("2026-10-01", "2026-10-04")
    assert "🟢🟡" in run("history", "rabbithole").stdout


def test_history_crossword(client):
    client.crosswords.return_value = [CrosswordListing(puzzleId="p1", author="Ann; edited by Ed", numWords=4,
                                                       publicationTime=1791086400000)]
    client.crossword_play.return_value = CrosswordPlay(id="p1", playState=2, timeTaken=95, nCorrectEntries=4,
                                                       revealUsed=True)
    rows = run_json("history", "crossword", "--from", "2026-10-04")
    assert rows[0]["status"] == "solved" and rows[0]["seconds"] == 95 and rows[0]["help"] == ["reveal"]
    client.crossword_play.assert_called_once_with("p1", "daily")


def test_stats(client):
    client.bracket_city_games.return_value = [
        bracket_game("2026-10-03", isComplete=True, totalKeystrokes=10, minimumKeystrokes=10),
        bracket_game("2026-10-04", isComplete=True, totalKeystrokes=20, minimumKeystrokes=10),
    ]
    client.rabbithole_games.return_value = [rabbithole_game("53", "2026-10-02", ["correct_first_try"], 3)]

    summary = run_json("stats")
    detail = run_json("stats", "bracket-city")

    assert summary[0] == {"game": "Bracket City", "played": 2, "completed": 2, "current_streak": 2,
                          "longest_streak": 2, "average_score": None}
    assert summary[1]["average_score"] == 3.0
    assert (detail["perfect"], round(detail["efficiency"], 3)) == (1, 0.667)
    assert "Keystroke efficiency" in run("stats", "bracket-city").stdout
    assert run_json("stats", "rabbithole")["perfect"] == 1


def test_today(client):
    client.rabbithole_puzzles.return_value = []
    client.game_states.return_value = [bracket_game("2026-10-04", solvedExpressions=["a"])]
    client.crosswords.return_value = []
    rows = run_json("today")
    assert rows == [{"game": "Bracket City", "status": "in progress", "detail": "1 clues solved"},
                    {"game": "Rabbithole", "status": "no puzzle", "detail": "published on weekdays"}]
    client.game_states.assert_called_once_with([("bracket-city", "2026-10-04", "v1")])


def test_archive_saves_skips_and_reports_missing(client, tmp_path):
    client.bracket_city_dates.return_value = ["2026-10-02", "2026-10-03"]
    client.bracket_city.return_value = BRACKET
    out = tmp_path / "archive"
    (out / "bracket-city").mkdir(parents=True)
    (out / "bracket-city" / "2026-10-03.json").write_text("{}")

    summary = run_json("archive", "bracket-city", "--from", "2026-10-01", "--to", "2026-10-03",
                       "-o", str(out), "--delay", "0")

    assert (summary["saved"], summary["skipped"], summary["missing"]) == (1, 1, ["2026-10-01"])
    saved = json.loads((out / "bracket-city" / "2026-10-02.json").read_text())
    assert saved["puzzleSolution"] == BRACKET.puzzleSolution
    client.bracket_city.assert_called_once_with("2026-10-02")
    manifest = json.loads((out / "bracket-city" / "manifest.json").read_text())["files"]
    assert len(manifest["2026-10-02.json"]["sha256"]) == 64


def test_archive_keeps_revisions(client, tmp_path):
    client.rabbithole_puzzles.return_value = [RABBITHOLE]
    out = tmp_path / "archive"
    args = ["archive", "rabbithole", "--from", "2026-10-02", "--to", "2026-10-02", "-o", str(out), "--delay", "0"]
    assert run_json(*args)["saved"] == 1
    assert run_json(*args, "--overwrite")["updated"] == []

    client.rabbithole_puzzles.return_value = [RABBITHOLE.model_copy(update={"byline": "Fixed"})]
    assert run_json(*args, "--overwrite")["updated"] == ["2026-10-02"]
    revisions = list((out / "rabbithole" / "revisions").iterdir())
    assert len(revisions) == 1 and json.loads(revisions[0].read_text())["byline"] == "Drew Goins"


ARCHIVE_ARGS = ["archive", "bracket-city", "--from", "2026-10-02", "--to", "2026-10-02", "--delay", "0",
                "-f", "json"]


def fail_replacing(monkeypatch, name):
    """Make os.replace fail when it would replace the file called `name`."""
    from atlgames import files
    real = files.os.replace

    def replace(src, dst):
        if Path(dst).name == name:
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(files.os, "replace", replace)


def test_archive_failed_update_keeps_the_file_and_manifest(client, tmp_path, monkeypatch):
    """A failed write never removes the saved puzzle or breaks the manifest (#12)."""
    out = tmp_path / "archive"
    client.bracket_city_dates.return_value = ["2026-10-02"]
    client.bracket_city.return_value = BRACKET
    run(*ARCHIVE_ARGS, "-o", str(out))
    saved = (out / "bracket-city" / "2026-10-02.json").read_bytes()
    manifest = (out / "bracket-city" / "manifest.json").read_text()

    client.bracket_city.return_value = BRACKET.model_copy(update={"author": "Fixed"})
    fail_replacing(monkeypatch, "2026-10-02.json")
    assert run(*ARCHIVE_ARGS, "-o", str(out), "--overwrite").exit_code != 0
    assert (out / "bracket-city" / "2026-10-02.json").read_bytes() == saved
    assert json.loads((out / "bracket-city" / "manifest.json").read_text()) == json.loads(manifest)
    leftovers = [p.name for p in (out / "bracket-city").rglob("*") if p.name.endswith(".tmp")]
    assert leftovers == []


def test_archive_failed_manifest_write_keeps_the_previous_manifest(client, tmp_path, monkeypatch):
    out = tmp_path / "archive"
    client.bracket_city_dates.return_value = ["2026-10-02"]
    client.bracket_city.return_value = BRACKET
    run(*ARCHIVE_ARGS, "-o", str(out))
    manifest = (out / "bracket-city" / "manifest.json").read_text()

    fail_replacing(monkeypatch, "manifest.json")
    assert run(*ARCHIVE_ARGS, "-o", str(out), "--overwrite").exit_code != 0
    assert (out / "bracket-city" / "manifest.json").read_text() == manifest


def test_archive_records_files_missing_from_the_manifest(client, tmp_path):
    """A file saved without a manifest entry, as by an interrupted run, is
    recorded as it is on the next run, and gets a revision when it changes."""
    out = tmp_path / "archive"
    (out / "bracket-city").mkdir(parents=True)
    (out / "bracket-city" / "2026-10-02.json").write_text("{}")
    client.bracket_city_dates.return_value = ["2026-10-02"]
    client.bracket_city.return_value = BRACKET

    assert json.loads(run(*ARCHIVE_ARGS, "-o", str(out)).stdout)["skipped"] == 1
    record = json.loads((out / "bracket-city" / "manifest.json").read_text())["files"]["2026-10-02.json"]
    assert record == {"date": "2026-10-02", "retrieved_at": None,
                      "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"}
    assert not client.bracket_city.called

    assert json.loads(run(*ARCHIVE_ARGS, "-o", str(out), "--overwrite").stdout)["updated"] == ["2026-10-02"]
    assert [p.name for p in (out / "bracket-city" / "revisions").iterdir()] == ["2026-10-02.unknown.json"]


def test_archive_crosswords_as_puz(client, tmp_path):
    client.crosswords.return_value = [CrosswordListing(puzzleId="atlantic_20261004",
                                                       publicationTime=1791086400000)]
    client.crossword.return_value = CROSSWORD
    summary = run_json("archive", "crossword", "--from", "2026-10-04", "--as", "puz", "-o", str(tmp_path),
                       "--delay", "0")
    assert summary["saved"] == 1
    assert (tmp_path / "crossword" / "2026-10-04.puz").read_bytes()[2:14] == b"ACROSS&DOWN\x00"
    client.crossword.assert_called_once_with(puzzle_id="atlantic_20261004", series="daily")
    assert run("archive", "rabbithole", "--as", "puz").exit_code == 2


def test_play_bracket_city(client):
    client.bracket_city.return_value = BRACKET
    result = run("play", "bracket-city", "2026-10-04", input="white\nrug\n/peek 2\n/reveal 2\nBLACK\n")
    assert result.exit_code == 0, result.output
    assert "Solved!" in result.stdout and "1 wrong guesses, 1 peeks, 1 reveals" in result.stdout
    assert "m__" in result.stdout and "Cats were domesticated" in result.stdout


def test_play_bracket_city_resume_and_quit(client):
    client.bracket_city.return_value = BRACKET
    client.bracket_city_game.return_value = bracket_game("2026-10-04", solvedExpressions=["color of snow"])
    result = run("play", "bracket-city", "2026-10-04", "--resume", input="/quit\n")
    assert result.exit_code == 0
    assert "opposite of white" in result.stdout and "Stopped with 1 of 3" in result.stdout


def test_play_rabbithole(client):
    client.rabbithole.return_value = RABBITHOLE
    result = run("play", "rabbithole", input="owls\n/hint\nathena\n")
    assert result.exit_code == 0, result.output
    assert "Score: 5 of 6" in result.stdout and "Nocturnal" not in result.stdout and "Greek" in result.stdout
    assert "https://example.com/owls" in result.stdout


def test_play_rabbithole_choices(client):
    client.rabbithole.return_value = RABBITHOLE
    result = run("play", "rabbithole", input="/choices\nOwl\n/skip\n")
    assert "Score: 1 of 6" in result.stdout and "It was Athena" in result.stdout


def test_cli_extra_message_when_typer_is_missing(monkeypatch):
    import atlgames.cli

    monkeypatch.setitem(sys.modules, "atlgames.cli.app", None)
    with pytest.raises(SystemExit) as exit_info:
        atlgames.cli.main()
    assert "atlantic-games[cli]" in str(exit_info.value)
