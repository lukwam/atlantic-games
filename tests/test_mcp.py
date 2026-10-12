"""MCP server tests, through an in-process MCP client with made-up data."""
import asyncio
import datetime
from unittest import mock

import pytest
from mcp import Client

from atlgames import AtlanticGamesAuthenticationError
from atlgames import AtlanticGamesNotFoundError
from atlgames import mcp_server
from atlgames.models import BracketCityGame
from atlgames.models import BracketCityPuzzle
from atlgames.models import CrosswordPuzzle
from atlgames.models import RabbitholeGame
from atlgames.models import RabbitholePuzzle
from atlgames.models import StacksPuzzle
from atlgames.models import TriviaArticle

BRACKET_CITY = BracketCityPuzzle(
    puzzleDate="2026-10-11", author="Someone", completionText="Well done",
    initialPuzzle="The [opposite of [color of the sky]] moon rises",
    puzzleSolution="The orange moon rises",
    solutions={"color of the sky": "blue", "opposite of blue": "orange"},
)
# 3x3 with a block in the middle: CAT / A#O / BOX.
CROSSWORD = CrosswordPuzzle(
    id="atlantic_20261011", title="Sunday", author="Ann Author; edited by Ed Editor", w=3, h=3,
    box=[["C", "A", "B"], ["A", "\x00", "O"], ["T", "O", "X"]],
    placedWords=[
        {"originalTerm": "CAT", "nBoxes": 3, "x": 0, "y": 0, "acrossNotDown": True, "clueNum": "1",
         "clue": {"clue": "<i>Feline</i>"}},
        {"originalTerm": "BOX", "nBoxes": 3, "x": 0, "y": 2, "acrossNotDown": True, "clueNum": "3",
         "clue": {"clue": "Crate"}},
        {"originalTerm": "CAB", "nBoxes": 3, "x": 0, "y": 0, "acrossNotDown": False, "clueNum": "1",
         "clue": {"clue": "Taxi"}},
        {"originalTerm": "TOX", "nBoxes": 3, "x": 2, "y": 0, "acrossNotDown": False, "clueNum": "2",
         "clue": {"clue": "Poison, briefly"}},
    ],
)
RABBITHOLE = RabbitholePuzzle(
    id="53", publishedAt="2026-10-09T10:00:00Z", byline="Drew Goins", recirculationBlurb="<em>Read</em> more",
    article={"id": "BlogArticle:1", "title": "About <em>Uno</em>", "url": "https://example.com/1"},
    questions=[
        {"id": "1", "questionText": "<div>What <strong>card game</strong>?</div>", "canonicalAnswer": "Uno",
         "validAnswers": ["Uno Flip"], "hintText": "<em>One</em>", "choices": ["Skip-Bo", "Phase 10"]},
        {"id": "2", "questionText": "<div>Uno's spin-off is named for what sport?</div>",
         "canonicalAnswer": "Golf", "hintText": "Clubs", "choices": ["Darts", "Polo"]},
        {"id": "3", "questionText": "<div>Golf's three under par is what bird?</div>",
         "canonicalAnswer": "Albatross", "validAnswers": ["Double eagle"], "choices": ["Gull", "Pelican"]},
    ],
)
TRIVIA = TriviaArticle(
    id="BlogArticle:688280", title="Atlantic Trivia", url="https://example.com/688280",
    datePublished="2026-08-14T10:00:00Z",
    questions=[{"id": "q1", "questionText": "<p>Which <b>planet</b> is red?</p>", "canonicalAnswer": "Mars",
                "hintText": "Fourth", "subtext": "<p>Iron oxide.</p>", "topicText": "Space",
                "relatedArticle": {"title": "Mars", "url": "https://example.com/mars"}}],
)
STACKS = StacksPuzzle(date="2026-08-24", id=433, wordStrings=["AB"], blackPos="--", solution=[0])


def bracket_game(date, progress="complete", **state):
    data = {"solvedExpressions": [], "totalKeystrokes": 10, "minimumKeystrokes": 8, "wrongGuesses": 1,
            "peekedClues": [], "solvedOnPubDate": True, **state}
    return BracketCityGame(gameKey=f"bracket-city#{date}#v1", gameSlug="bracket-city", gameDate=date,
                           gameId="v1", progress=progress, gameState=data)


def rabbithole_game(results, progress="inProgress", score=3):
    return RabbitholeGame(gameKey="rabbithole#2026-10-09#53", gameSlug="rabbithole", gameDate="2026-10-09",
                          gameId="53", progress=progress,
                          gameState={"questionResults": results, "score": score})


@pytest.fixture
def atl(monkeypatch):
    """Replace the server's Atlantic client with a mock."""
    fake = mock.AsyncMock()
    fake.__aenter__.return_value = fake
    fake.account = None
    fake.bracket_city.return_value = BRACKET_CITY
    fake.bracket_city_game.return_value = None
    fake.crossword.return_value = CROSSWORD
    fake.rabbithole.return_value = RABBITHOLE
    fake.trivia.return_value = TRIVIA
    fake.stacks.return_value = STACKS
    monkeypatch.setattr(mcp_server, "client", lambda: fake)
    monkeypatch.setattr(mcp_server, "today", lambda: datetime.date(2026, 10, 11))
    return fake


def call(name, arguments=None):
    async def run():
        async with Client(mcp_server.server) as client:
            return await client.call_tool(name, arguments or {})
    return asyncio.run(run())


def data(result):
    assert not result.is_error, result.content[0].text
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content


def error(result):
    assert result.is_error
    return result.content[0].text


def test_tools_are_listed_with_descriptions_and_annotations():
    async def run():
        async with Client(mcp_server.server) as client:
            return (await client.list_tools()).tools
    tools = {t.name: t for t in asyncio.run(run())}
    assert set(tools) == {
        "bracket_city", "check_bracket_city_answer", "bracket_city_peek", "crossword", "check_crossword_answer",
        "crossword_archive", "crossword_progress", "rabbithole", "check_rabbithole_answer", "rabbithole_archive",
        "trivia_archive", "trivia", "check_trivia_answer", "stacks", "games", "account", "bracket_city_history",
        "bracket_city_stats", "rabbithole_history", "rabbithole_stats", "export_crossword",
    }
    for name, t in tools.items():
        assert t.description and len(t.description) > 40, name
        assert t.annotations.read_only_hint is (name != "export_crossword"), name
    assert tools["export_crossword"].annotations.destructive_hint is False
    assert tools["crossword"].input_schema["properties"]["series"]["enum"] == ["daily", "inferno"]


def test_bracket_city_hides_answers_unless_asked(atl):
    hidden = data(call("bracket_city"))
    assert hidden["puzzle"] == BRACKET_CITY.initialPuzzle
    assert hidden["available"] == [{"number": 2, "clue": "color of the sky", "depth": 2}]
    assert "blue" not in str(hidden) and "orange" not in str(hidden) and "Well done" not in str(hidden)
    atl.bracket_city.assert_called_with(None)

    partly = data(call("bracket_city", {"date": "2026-10-11", "solved": [2]}))
    assert partly["puzzle"] == "The [opposite of blue] moon rises" and partly["solved_count"] == 1
    assert partly["available"] == [{"number": 1, "clue": "opposite of blue", "depth": 1}]
    assert data(call("bracket_city", {"solved": ["color of the sky"]}))["solved_count"] == 1

    shown = data(call("bracket_city", {"include_answers": True}))
    assert [c["answer"] for c in shown["clues"]] == ["orange", "blue"]
    assert shown["solution"] == "The orange moon rises" and "caption" not in shown
    assert "No clue 7" in error(call("bracket_city", {"solved": [7]}))


def test_bracket_city_saved_progress(atl):
    atl.bracket_city_game.return_value = bracket_game("2026-10-11", "inProgress",
                                                      solvedExpressions=["color of the sky"])
    view = data(call("bracket_city", {"use_saved_progress": True}))
    assert view["puzzle"] == "The [opposite of blue] moon rises"
    assert view["saved_game"] == {"progress": "inProgress", "wrong_guesses": 1, "peeks": 0, "mega_peeks": 0}
    atl.bracket_city_game.assert_called_with("2026-10-11")


def test_bracket_city_check_and_peek(atl):
    assert data(call("check_bracket_city_answer", {"clue": 2, "guess": "red"})) == {
        "date": "2026-10-11", "number": 2, "clue": "color of the sky", "correct": False}
    right = data(call("check_bracket_city_answer", {"clue": "[color of the sky]", "guess": " Blue!"}))
    assert right["correct"] and right["answer"] == "blue"
    peek = data(call("bracket_city_peek", {"clue": "1"}))
    assert peek["first_letter"] == "o" and peek["length"] == 6 and "answer" not in peek
    assert data(call("bracket_city_peek", {"clue": 1, "full": True}))["answer"] == "orange"
    assert "numbered 1 to 2" in error(call("bracket_city_peek", {"clue": 0}))
    assert "No clue 'nope'" in error(call("bracket_city_peek", {"clue": "nope"}))


def test_crossword_entries(atl):
    hidden = data(call("crossword", {"date": "2026-10-11"}))
    assert hidden["grid"] == ["...", ".#.", "..."]
    assert hidden["constructor"] == "Ann Author" and hidden["editor"] == "Ed Editor"
    assert hidden["id"] == "atlantic_20261011" and hidden["size"] == "3x3" and "clues" not in hidden
    assert hidden["entries"][0] == {"id": "1-Across", "direction": "Across", "clue": "Feline", "length": 3,
                                    "start": [0, 0], "crossings": ["1-Down", "2-Down"]}
    atl.crossword.assert_called_with(date="2026-10-11", series="daily")
    shown = data(call("crossword", {"series": "inferno", "puzzle_id": "x1", "include_answers": True}))
    assert shown["grid"] == ["CAT", "A#O", "BOX"] and shown["entries"][1]["answer"] == "BOX"
    atl.crossword.assert_called_with(puzzle_id="x1", series="inferno")


def test_check_crossword_answer(atl):
    wrong = data(call("check_crossword_answer", {"entry": "2-down", "guess": "TO"}))
    assert not wrong["correct"] and "answer" not in wrong and wrong["note"] == "The answer has 3 squares"
    assert data(call("check_crossword_answer", {"entry": "2 Down", "guess": "t-o-x"}))["answer"] == "TOX"
    revealed = data(call("check_crossword_answer", {"entry": "3-Across", "guess": "BIN", "reveal": True}))
    assert revealed["answer"] == "BOX"
    assert "No entry" in error(call("check_crossword_answer", {"entry": "9-Across", "guess": "X"}))


def test_crossword_progress(atl):
    from atlgames.models import CrosswordPlay
    atl.crossword_play.return_value = CrosswordPlay(id="atlantic_20261011", playState=2, timeTaken=300,
                                                    nCorrectEntries=4, revealUsed=False)
    progress = data(call("crossword_progress"))
    assert progress["status"] == "solved" and progress["seconds"] == 300 and progress["correct_entries"] == 4
    assert progress["entries"] == 4 and progress["help"] == []
    atl.crossword_play.assert_called_with("atlantic_20261011", "daily")


def test_rabbithole_shows_questions_up_to_the_current_one(atl):
    first = data(call("rabbithole"))
    assert first["questions"] == [{"number": 1, "question": "What card game?"}]
    assert "article" not in first and "blurb" not in first

    second = data(call("rabbithole", {"answered": 1, "include_hints": True, "include_choices": True}))
    assert second["questions"][0]["answer"] == "Uno"
    assert second["questions"][1] == {"number": 2, "question": "Uno's spin-off is named for what sport?",
                                      "hint": "Clubs", "choices": ["Darts", "Golf", "Polo"]}

    shown = data(call("rabbithole", {"include_answers": True}))
    assert [q["answer"] for q in shown["questions"]] == ["Uno", "Golf", "Albatross"]
    assert shown["article"]["title"] == "About Uno" and shown["blurb"] == "Read more"


def test_rabbithole_saved_progress_and_check(atl):
    atl.rabbithole_game.return_value = rabbithole_game(["correct_first_try", "incorrect"])
    view = data(call("rabbithole", {"use_saved_progress": True}))
    assert view["answered"] == 2 and len(view["questions"]) == 3 and "answer" not in view["questions"][2]
    assert view["saved_game"]["results"] == ["correct_first_try", "incorrect"]

    right = data(call("check_rabbithole_answer", {"question": 1, "guess": "uno flip"}))
    assert right == {"id": "53", "question": 1, "correct": True, "answer": "Uno",
                     "next_question": "Uno's spin-off is named for what sport?"}
    assert data(call("check_rabbithole_answer", {"question": 3, "guess": "Double Eagle"}))["correct"]
    wrong = data(call("check_rabbithole_answer", {"question": 2, "guess": "tennis"}))
    assert wrong == {"id": "53", "question": 2, "correct": False}
    assert data(call("check_rabbithole_answer", {"question": 2, "guess": "x", "reveal": True}))["answer"] == "Golf"
    assert "questions 1 to 3" in error(call("check_rabbithole_answer", {"question": 4, "guess": "x"}))


def test_rabbithole_archive_hides_answers(atl):
    atl.rabbithole_puzzles.return_value = [RABBITHOLE]
    assert data(call("rabbithole_archive")) == [{"date": "2026-10-09", "id": "53", "byline": "Drew Goins",
                                                 "question_count": 3}]
    atl.rabbithole_puzzles.assert_called_with("2026-09-12", "2026-10-11")
    assert "after date_end" in error(call("rabbithole_archive", {"date_start": "2026-10-11",
                                                                 "date_end": "2026-10-01"}))


def test_trivia_and_stacks(atl):
    quiz = data(call("trivia", {"article": "688280"}))
    assert quiz["questions"] == [{"number": 1, "topic": "Space", "question": "Which planet is red?"}]
    shown = data(call("trivia", {"article": "688280", "include_hints": True, "include_answers": True}))
    assert shown["questions"][0]["answer"] == "Mars" and shown["questions"][0]["explanation"] == "Iron oxide."
    assert data(call("check_trivia_answer", {"article": "688280", "question": 1, "guess": "mars"}))["correct"]

    puzzle = data(call("stacks", {"date": "2026-08-24"}))
    assert puzzle == {"date": "2026-08-24", "id": 433, "title": "", "words": ["AB"], "base": "--"}
    shown = data(call("stacks", {"date": "2026-08-24", "include_answers": True}))
    assert shown["board"] == ["AB"] and shown["drops"] == [{"word": "AB", "column": 1}]


def test_stats_and_history_need_cookies(atl):
    atl.bracket_city_games.side_effect = AtlanticGamesAuthenticationError("This needs you to be logged in")
    message = error(call("bracket_city_stats"))
    assert "atlg auth login" in message and "ATLANTIC_COOKIES" in message
    assert data(call("account"))["logged_in"] is False


def test_stats_and_history(atl):
    atl.bracket_city_games.return_value = [bracket_game("2026-10-10"), bracket_game("2026-10-11")]
    stats = data(call("bracket_city_stats"))
    assert stats["completed"] == 2 and stats["current_streak"] == 2 and stats["efficiency"] == 0.8
    assert stats["first_completed"] == "2026-10-10" and "completed_dates" not in stats
    atl.bracket_city_games.assert_called_with(None, "2026-10-11")
    atl.bracket_city_dates.return_value = ["2026-10-09", "2026-10-10", "2026-10-11"]
    rows = data(call("bracket_city_history", {"date_start": "yesterday"}))
    assert [r["date"] for r in rows] == ["2026-10-11", "2026-10-10"]
    assert rows[1] == {"date": "2026-10-10", "status": "complete", "solved_clues": 0, "wrong_guesses": 1,
                       "keystrokes": 10, "minimum_keystrokes": 8, "efficiency": 0.8, "peeks": 0, "hints": 0,
                       "solved_on_the_day": True}
    atl.bracket_city_games.assert_called_with("2026-10-10", "2026-10-11")

    atl.rabbithole_games.return_value = [rabbithole_game(["correct_first_try"] * 3, "complete", 9)]
    assert data(call("rabbithole_stats"))["perfect"] == 1
    atl.rabbithole_puzzles.return_value = [RABBITHOLE]
    assert data(call("rabbithole_history")) == [{"date": "2026-10-09", "id": "53", "status": "complete",
                                                 "score": 9, "max_score": 9,
                                                 "results": ["correct_first_try"] * 3}]


def test_errors_are_actionable(atl):
    atl.crossword.side_effect = AtlanticGamesNotFoundError("No daily crossword for 1900-01-01")
    assert "Not found: No daily crossword" in error(call("crossword", {"date": "1900-01-01"}))
    assert "Invalid date" in error(call("bracket_city", {"date": "someday"}))


def test_cookies_come_from_the_environment_then_the_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLG_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ATLG_PROFILE", raising=False)
    monkeypatch.delenv("ATLANTIC_COOKIES", raising=False)
    assert mcp_server.cookies() is None
    (tmp_path / "config.ini").write_text("[default]\ncookies = atljwt6=fromprofile\n")
    assert mcp_server.cookies() == "atljwt6=fromprofile"
    monkeypatch.setenv("ATLANTIC_COOKIES", "atljwt6=fromenv")
    assert mcp_server.cookies() == "atljwt6=fromenv"


def test_cookie_errors_never_show_values(monkeypatch):
    monkeypatch.setenv("ATLANTIC_COOKIES", "atljwt6=SECRET\nVALUE")
    message = error(call("account"))
    assert "SECRET" not in message and "atljwt6" in message


def test_export_crossword_writes_a_file(atl, tmp_path):
    import puz
    target = tmp_path / "out" / "cw.puz"
    saved = data(call("export_crossword", {"path": str(target), "date": "2026-10-11"}))
    assert saved["path"] == str(target.resolve()) and saved["format"] == "puz" and saved["bytes"] > 0
    assert any("italics" in note for note in saved["notes"])
    assert puz.read(str(target)).solution == "CATA.OBOX"  # CAT / A#O / BOX
    assert "already exists" in error(call("export_crossword", {"path": str(target)}))
    assert data(call("export_crossword", {"path": str(target), "overwrite": True}))["bytes"] > 0
    assert ".puz, .ipuz or .xml" in error(call("export_crossword", {"path": str(tmp_path / "cw.pdf")}))
