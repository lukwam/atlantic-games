"""Plain data views of puzzles and saved games, shared by atlg and the MCP server.

Each view returns JSON-compatible data. Puzzle views hide answers unless
`answers` is true. Some games give answers away in unexpected places, so
those are hidden too: each Rabbithole question names the previous question's
answer, and Bracket City's nested clues contain their inner clues' answers
once resolved.

Clues and questions are numbered from 1, as the games show them.
"""
import dataclasses
from collections.abc import Iterable
from typing import Any

from atlgames.auth import Account
from atlgames.models import BracketCityGame
from atlgames.models import BracketCityPuzzle
from atlgames.models import CrosswordListing
from atlgames.models import CrosswordPlay
from atlgames.models import CrosswordPuzzle
from atlgames.models import Game
from atlgames.models import GameState
from atlgames.models import RabbitholeGame
from atlgames.models import RabbitholePuzzle
from atlgames.models import StacksPuzzle
from atlgames.models import TriviaArticle
from atlgames.models import strip_html

RABBITHOLE_RESULTS = {
    "correct_first_try": 3,
    "correct_with_hint": 2,
    "correct_with_choice": 1,
    "incorrect": 0,
}


# Puzzles


def bracket_city_view(puzzle: BracketCityPuzzle, answers: bool = False, clues: bool = False,
                      steps: bool = False, solved: Iterable[int] | None = None,
                      saved: BracketCityGame | None = None) -> dict:
    """A Bracket City puzzle: the bracketed text, and the clues or answers if asked.

    `clues` lists every clue, with its answer if `answers`; `steps` adds a
    solving order (which shows the answers). For playing along, `solved`
    lists clue numbers already solved and `saved` adds the clues solved in a
    saved game: their answers are filled into the text, and the clues that
    can be solved now are listed.
    """
    all_clues = puzzle.clues()
    progress = solved is not None or saved is not None
    done = {number - 1 for number in solved or ()}
    if saved is not None:
        texts = set(saved.data.solvedExpressions)
        done.update(c.index for c in all_clues if c.text in texts)
    data: dict[str, Any] = {
        "date": puzzle.puzzleDate,
        "author": puzzle.author,
        "puzzle": puzzle.render(sorted(done)),
        "clue_count": len(all_clues),
        "depth": puzzle.depth,
    }
    if progress:
        data["solved_count"] = len(done)
        data["available"] = [{"number": c.index + 1, "clue": c.text, "depth": c.depth}
                             for c in puzzle.available(sorted(done))]
    if saved is not None:
        game = saved.data
        data["saved_game"] = {"progress": saved.progress.value, "wrong_guesses": game.wrongGuesses,
                              "peeks": len(game.peekedClues), "mega_peeks": len(game.megaPeekedClues)}
    if clues or answers:
        data["clues"] = [
            {"number": c.index + 1, "depth": c.depth, "parent": None if c.parent is None else c.parent + 1,
             "clue": clue_outline(puzzle, c),
             **({"resolved": c.text, "answer": c.answer} if answers else {})}
            for c in all_clues
        ]
    if answers or len(done) == len(all_clues):
        data["solution"] = puzzle.solved_text
        data["completion_text"] = puzzle.completionText
    if answers:
        if not puzzle.caption_matches:
            data["caption"] = puzzle.puzzleSolution
        data["completion_url"] = puzzle.completionURL
    if steps:
        data["steps"] = [{"step": n, "number": c.index + 1, "clue": c.text, "answer": c.answer}
                         for n, c in enumerate(puzzle.steps(), 1)]
    return data


def clue_outline(puzzle: BracketCityPuzzle, clue) -> str:
    """A clue with the clues directly inside it shown as [#N], so nothing is
    given away and long clues stay readable."""
    text = clue.raw
    for child in clue.children:
        text = text.replace(f"[{puzzle.clues()[child].raw}]", f"[#{child + 1}]", 1)
    return text


def crossword_view(puzzle: CrosswordPuzzle, answers: bool = False, clues: bool = True,
                   entries: bool = False) -> dict:
    """A crossword's grid and clues; `entries` adds each entry's position and crossings."""
    grid = ["".join("#" if letter is None else (letter[:1] if answers else ".") for letter in row)
            for row in puzzle.grid()]
    data: dict[str, Any] = {
        "date": puzzle.date,
        "series": puzzle.series,
        "id": puzzle.id,
        "title": strip_html(puzzle.title),
        "constructor": puzzle.constructor,
        "editor": puzzle.editor,
        "size": f"{puzzle.w}x{puzzle.h}",
        "grid": grid,
    }
    if puzzle.description:
        data["notes"] = strip_html(puzzle.description)
    if clues:
        lists: dict[str, list] = {"across": [], "down": []}
        for entry in puzzle.entries():
            item = {"label": entry.label or "", "clue": strip_html(entry.clue), "length": len(entry.cells)}
            if answers:
                item["answer"] = entry.answer
            lists[entry.direction.lower()].append(item)
        data["clues"] = lists
    if entries:
        data["entries"] = []
        for entry in puzzle.entries():
            item = {"id": entry.id, "direction": entry.direction, "clue": strip_html(entry.clue),
                    "length": len(entry.cells), "start": list(entry.coordinates[0]),
                    "crossings": list(entry.crossings)}
            if answers:
                item["answer"] = entry.answer
            data["entries"].append(item)
    return data


def crossword_listing_row(listing: CrosswordListing) -> dict:
    return {
        "date": listing.date,
        "id": listing.puzzleId,
        "title": strip_html(listing.title),
        "author": listing.author.split(";")[0].strip(),
        "size": f"{listing.gridWidth}x{listing.gridHeight}" if listing.gridWidth else None,
    }


def rabbithole_view(puzzle: RabbitholePuzzle, answers: bool = False, answered: int = 0,
                    hints: bool = False, choices: bool = False) -> dict:
    """A Rabbithole puzzle: the questions up to the one being solved.

    Each question names the previous answer, so only the `answered`
    questions (with their answers) and the next one are shown, or every
    question and answer with `answers`. `hints` adds the game's hints, and
    `choices` the multiple choice options (the right answer and two wrong
    ones, sorted).
    """
    total = len(puzzle.questions)
    answered = total if answers else max(0, min(answered, total))
    shown = total if answers else min(answered + 1, total)
    questions = []
    for number, q in enumerate(puzzle.questions[:shown], 1):
        item: dict[str, Any] = {"number": number, "question": q.question}
        if number <= answered:
            item["answer"] = q.canonicalAnswer
        if answers:
            item["valid_answers"] = q.validAnswers
        if hints or answers:
            item["hint"] = q.hint
        if choices or answers:
            item["choices"] = sorted([*q.choices, q.canonicalAnswer], key=str.casefold)
        questions.append(item)
    data: dict[str, Any] = {
        "id": puzzle.id,
        "date": puzzle.date,
        "byline": puzzle.byline,
        "question_count": total,
        "max_score": puzzle.max_score,
        "answered": answered,
        "questions": questions,
    }
    if answered == total:
        if puzzle.article:
            data["article"] = {"title": strip_html(puzzle.article.title), "url": puzzle.article.url}
        if puzzle.recirculationBlurb:
            data["blurb"] = strip_html(puzzle.recirculationBlurb)
    return data


def rabbithole_listing_row(puzzle: RabbitholePuzzle) -> dict:
    return {"date": puzzle.date, "id": puzzle.id, "byline": puzzle.byline,
            "question_count": len(puzzle.questions)}


def trivia_view(article: TriviaArticle, answers: bool = False, hints: bool = False) -> dict:
    """A day's Trivia questions, with hints, and answers and explanations, if asked."""
    questions = []
    for n, q in enumerate(article.questions, 1):
        item: dict[str, Any] = {"number": n, "topic": q.topicText, "question": q.question}
        if (hints or answers) and q.hintText:
            item["hint"] = strip_html(q.hintText)
        if answers:
            item.update(answer=q.canonicalAnswer, valid_answers=q.validAnswers,
                        explanation=strip_html(q.subtext))
            if q.relatedArticle:
                item["article"] = {"title": strip_html(q.relatedArticle.title), "url": q.relatedArticle.url}
        questions.append(item)
    return {"id": article.article_id, "date": article.date, "title": strip_html(article.title),
            "url": article.url, "questions": questions}


def trivia_listing_row(article: TriviaArticle) -> dict:
    return {"date": article.date, "id": article.article_id, "title": strip_html(article.title),
            "url": article.url}


def stacks_view(puzzle: StacksPuzzle, answers: bool = False) -> dict:
    """A Stacks puzzle: the words to drop and the base row, and the solution if asked."""
    data = {"date": puzzle.date, "id": puzzle.id, "title": puzzle.title,
            "words": puzzle.wordStrings, "base": puzzle.blackPos}
    if answers:
        data["drops"] = [{"word": d.word, "column": d.column + 1} for d in puzzle.drops()]
        data["board"] = puzzle.rows()
    return data


def game_row(game: Game) -> dict:
    """A game on the games hub."""
    return {"slug": game.slug, "name": game.name, "author": game.author, "archive": game.hasArchive,
            "featured": game.isFeaturedGame,
            "description": strip_html(game.shortDescription or game.description or ""), "url": game.url}


# Your account and results


def account_view(account: Account) -> dict:
    """When the login expires and the subscription flags, read from the cookies."""
    return {"expires": account.expires_at.isoformat() if account.expires_at else None,
            "expired": account.expired, "premium_access": account.premium_access, "ad_free": account.ad_free}


def status_of(game: GameState | None) -> str:
    """Return complete, in progress or not played."""
    if game is None or (game.progress.value == "notStarted" and not (game.gameState or {}).get(
            "solvedExpressions") and not (game.gameState or {}).get("questionResults")):
        return "not played"
    return "complete" if game.complete else "in progress"


def bracket_city_result(day: str, game: BracketCityGame | None) -> dict:
    """One date's Bracket City result from a saved game."""
    data = game.data if game else None
    status = status_of(game)
    played = status != "not played"
    return {
        "date": day,
        "status": status,
        "solved_clues": len(data.solvedExpressions) if played else 0,
        "wrong_guesses": data.wrongGuesses if played else None,
        "keystrokes": data.totalKeystrokes if played else None,
        "minimum_keystrokes": data.minimumKeystrokes if played else None,
        "efficiency": round(game.efficiency, 3) if played and game.efficiency is not None else None,
        "peeks": len(data.peekedClues) + len(data.megaPeekedClues) if played else None,
        "hints": len(data.hintModeClues) if played else None,
        "solved_on_the_day": data.solvedOnPubDate if played else None,
    }


def bracket_city_results(dates: Iterable[str], games: Iterable[BracketCityGame]) -> list[dict]:
    """Bracket City results for dates, newest first; dates without a saved game are not played."""
    saved = {g.gameDate: g for g in games}
    return [bracket_city_result(d, saved.get(d)) for d in sorted(dates, reverse=True)]


def rabbithole_result(puzzle: RabbitholePuzzle, game: RabbitholeGame | None) -> dict:
    """One Rabbithole puzzle's result from a saved game."""
    status = status_of(game)
    data = game.data if game else None
    return {
        "date": puzzle.date,
        "id": puzzle.id,
        "status": status,
        "score": data.score if data and status != "not played" else None,
        "max_score": puzzle.max_score,
        "results": data.questionResults if data else [],
    }


def rabbithole_results(puzzles: Iterable[RabbitholePuzzle], games: Iterable[RabbitholeGame]) -> list[dict]:
    """Rabbithole results for puzzles, in their order; puzzles without a saved game are not played."""
    saved = {g.gameId: g for g in games}
    return [rabbithole_result(p, saved.get(p.id)) for p in puzzles]


def crossword_result(listing: CrosswordListing | CrosswordPuzzle, play: CrosswordPlay | None) -> dict:
    """One crossword's result from Amuse Labs' saved play, for a listing or a puzzle."""
    if isinstance(listing, CrosswordPuzzle):
        puzzle_id, title, author, entries = listing.id, listing.title, listing.author, len(listing.entries())
    else:
        puzzle_id, title, author, entries = listing.puzzleId, listing.title, listing.author, listing.numWords
    started = bool(play and play.started)
    solved = bool(started and entries and play.nCorrectEntries == entries)
    return {
        "date": listing.date,
        "id": puzzle_id,
        "title": strip_html(title),
        "author": author.split(";")[0].strip(),
        "status": "solved" if solved else "started" if started else "not played",
        "seconds": play.timeTaken if started else None,
        "correct_entries": play.nCorrectEntries if started else None,
        "entries": entries,
        "help": [name for name in ("check", "reveal", "hint")
                 if started and getattr(play, f"{name}Used")],
    }


def stats_view(record) -> dict:
    """A stats record (from atlgames.stats) as a dict, with floats rounded and
    the list of completed dates reduced to the first and last."""
    data = dataclasses.asdict(record)
    for key, value in data.items():
        if isinstance(value, float):
            data[key] = round(value, 3)
    if "completed_dates" in data:
        completed = data.pop("completed_dates")
        data["first_completed"] = completed[0] if completed else None
        data["last_completed"] = completed[-1] if completed else None
    return data
