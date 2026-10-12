"""JSON-compatible views of puzzles and saved games, for atlg's output formats.

Answers are left out unless asked for. Some games give answers away in
unexpected places, so those are hidden too: each Rabbithole question names
the previous question's answer, and Bracket City's nested clues contain
their inner clues' answers once resolved.
"""
from atlgames.models import BracketCityGame
from atlgames.models import BracketCityPuzzle
from atlgames.models import CrosswordListing
from atlgames.models import CrosswordPlay
from atlgames.models import CrosswordPuzzle
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


def bracket_city_view(puzzle: BracketCityPuzzle, answers: bool = False, clues: bool = False,
                      steps: bool = False) -> dict:
    """A Bracket City puzzle: the bracketed text, and the clues or answers if asked."""
    data = {
        "date": puzzle.puzzleDate,
        "author": puzzle.author,
        "puzzle": puzzle.initialPuzzle,
        "clues": len(puzzle.clues()),
        "depth": puzzle.depth,
    }
    if clues or answers:
        data["clue_list"] = [
            {"number": c.index + 1, "depth": c.depth, "parent": None if c.parent is None else c.parent + 1,
             "clue": clue_outline(puzzle, c),
             **({"resolved": c.text, "answer": c.answer} if answers else {})}
            for c in puzzle.clues()
        ]
    if answers:
        data["solution"] = puzzle.solved_text
        if not puzzle.caption_matches:
            data["caption"] = puzzle.puzzleSolution
        data["completion_text"] = puzzle.completionText
        data["completion_url"] = puzzle.completionURL
    if steps:
        data["steps"] = [{"step": n, "index": c.index, "clue": c.text, "answer": c.answer}
                         for n, c in enumerate(puzzle.steps(), 1)]
    return data


def clue_outline(puzzle: BracketCityPuzzle, clue) -> str:
    """A clue with the clues directly inside it shown as [#N], so nothing is
    given away and long clues stay readable."""
    text = clue.raw
    for child in clue.children:
        text = text.replace(f"[{puzzle.clues()[child].raw}]", f"[#{child + 1}]", 1)
    return text


def crossword_view(puzzle: CrosswordPuzzle, answers: bool = False, clues: bool = True) -> dict:
    """A crossword's grid and clues, filled in with answers."""
    grid = ["".join("#" if letter is None else (letter[:1] if answers else ".") for letter in row)
            for row in puzzle.grid()]
    data = {
        "date": puzzle.date,
        "series": puzzle.series,
        "id": puzzle.id,
        "title": puzzle.title,
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
    return data


def crossword_listing_row(listing: CrosswordListing) -> dict:
    return {
        "date": listing.date,
        "id": listing.puzzleId,
        "title": listing.title,
        "author": listing.author.split(";")[0].strip(),
        "size": f"{listing.gridWidth}x{listing.gridHeight}" if listing.gridWidth else None,
    }


def rabbithole_view(puzzle: RabbitholePuzzle, answers: bool = False) -> dict:
    """A Rabbithole puzzle. Without answers, only the first question: each
    question after it names the answer before."""
    data = {
        "id": puzzle.id,
        "date": puzzle.date,
        "byline": puzzle.byline,
        "questions": len(puzzle.questions),
        "max_score": puzzle.max_score,
    }
    if not answers:
        if puzzle.questions:
            data["first_question"] = puzzle.questions[0].question
        return data
    data["question_list"] = [
        {"number": n, "question": q.question, "answer": q.canonicalAnswer,
         "valid_answers": q.validAnswers, "hint": q.hint, "choices": q.choices}
        for n, q in enumerate(puzzle.questions, 1)
    ]
    if puzzle.article:
        data["article"] = {"title": strip_html(puzzle.article.title), "url": puzzle.article.url}
    if puzzle.recirculationBlurb:
        data["blurb"] = strip_html(puzzle.recirculationBlurb)
    return data


def rabbithole_listing_row(puzzle: RabbitholePuzzle) -> dict:
    return {"date": puzzle.date, "id": puzzle.id, "byline": puzzle.byline, "questions": len(puzzle.questions)}


def trivia_view(article: TriviaArticle, answers: bool = False) -> dict:
    """A day's Trivia questions, with answers and explanations if asked."""
    questions = []
    for n, q in enumerate(article.questions, 1):
        item = {"number": n, "topic": q.topicText, "question": q.question}
        if answers:
            item.update(answer=q.canonicalAnswer, valid_answers=q.validAnswers,
                        hint=strip_html(q.hintText), explanation=strip_html(q.subtext))
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


def crossword_result(listing: CrosswordListing, play: CrosswordPlay | None) -> dict:
    """One crossword's result from Amuse Labs' saved play."""
    started = bool(play and play.started)
    solved = bool(started and listing.numWords and play.nCorrectEntries == listing.numWords)
    return {
        "date": listing.date,
        "id": listing.puzzleId,
        "title": listing.title,
        "author": listing.author.split(";")[0].strip(),
        "status": "solved" if solved else "started" if started else "not played",
        "seconds": play.timeTaken if started else None,
        "correct_entries": play.nCorrectEntries if started else None,
        "entries": listing.numWords,
        "help": [name for name in ("check", "reveal", "hint")
                 if started and getattr(play, f"{name}Used")],
    }
