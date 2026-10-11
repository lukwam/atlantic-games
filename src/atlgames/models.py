"""Atlantic Games models.

Field names follow the services' own JSON, so nothing is lost converting
back; properties and methods add friendlier views. Extra fields are kept,
so new fields from The Atlantic or Amuse Labs don't break validation.
"""
import datetime
import difflib
import re
import unicodedata
from enum import Enum
from functools import cached_property
from typing import Any
from typing import Dict
from typing import List
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from atlgames import bracket_city
from atlgames import stacks

EASTERN = ZoneInfo("America/New_York")


class AtlanticModel(BaseModel):
    """Base model. Extra fields are allowed and passed through."""
    model_config = ConfigDict(extra="allow", ignored_types=(cached_property,))


def _eastern_date(when: datetime.datetime | None) -> str | None:
    return when.astimezone(EASTERN).date().isoformat() if when else None


def _ms(value: int | float | None) -> datetime.datetime | None:
    if not value:
        return None
    return datetime.datetime.fromtimestamp(value / 1000, datetime.timezone.utc)


_TAGS = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str | None:
    """Return text without HTML tags or entities, for display."""
    if text is None:
        return None
    import html
    return " ".join(html.unescape(_TAGS.sub("", text)).split())


# Bracket City

class BracketCityPuzzle(AtlanticModel):
    """A Bracket City puzzle.

    `solutions` maps each clue's resolved text to its answer. Use the
    structure methods (`clues()`, `render()`, `available()`, `steps()`) to
    work with the nesting, and `solved_text` for the final text the game
    shows (`puzzleSolution` is an editorial caption that occasionally differs).
    """
    puzzleDate: str
    initialPuzzle: str
    puzzleSolution: str
    solutions: Dict[str, str]
    completionText: str = ""
    completionURL: str = ""
    author: str | None = None

    @cached_property
    def tree(self) -> bracket_city.Tree:
        return bracket_city.Tree(self.initialPuzzle, self.solutions)

    def clues(self) -> tuple[bracket_city.Clue, ...]:
        """Every clue, in the order its bracket opens."""
        return self.tree.clues

    def render(self, solved=(), mark=None) -> str:
        """The text with the solved clues (clues, indexes or texts) answered."""
        return self.tree.render(solved, mark)

    def available(self, solved=()) -> list[bracket_city.Clue]:
        """The clues that can be solved next."""
        return self.tree.available(solved)

    def steps(self) -> list[bracket_city.Clue]:
        """The clues in an order that solves the puzzle, innermost first."""
        return self.tree.steps()

    @property
    def solved_text(self) -> str:
        """The text with every clue solved: what the game shows at the end."""
        return self.tree.solved_text

    @property
    def caption_matches(self) -> bool:
        """False when `puzzleSolution` differs from the solved text."""
        return self.solved_text == self.puzzleSolution

    @property
    def depth(self) -> int:
        """How deeply the clues nest."""
        return max((clue.depth for clue in self.clues()), default=0)


# Crosswords (Amuse Labs)

class CrosswordSeries(str, Enum):
    """Amuse Labs series for The Atlantic's crosswords."""
    daily = "atlantic"
    inferno = "atlantic-inferno"

    @classmethod
    def coerce(cls, value: "CrosswordSeries | str") -> "CrosswordSeries":
        if isinstance(value, cls):
            return value
        try:
            return cls[value]
        except KeyError:
            return cls(value)


class CrosswordClue(AtlanticModel):
    clue: str = ""


class CrosswordPlacedWord(AtlanticModel):
    """One entry as Amuse Labs stores it. `x` is the column and `y` the row."""
    originalTerm: str
    nBoxes: int
    x: int
    y: int
    acrossNotDown: bool
    clueNum: str | None = None
    clue: CrosswordClue = Field(default_factory=CrosswordClue)
    wordLens: List[int] = []


class CrosswordPuzzle(AtlanticModel):
    """A crossword from Amuse Labs, with its solution.

    `box` is column-major (`box[x][y]`) and uses "\\u0000" for black squares;
    `grid()` returns rows. Use `entries()` and `squares()` for the structure.
    """
    id: str
    title: str = ""
    subtitle: str = ""
    description: str = ""
    author: str = ""
    copyright: str = ""
    puzzleType: str = "CROSSWORD"
    w: int
    h: int
    box: List[List[str | None]]
    clueNums: List[List[str | None]] = []
    placedWords: List[CrosswordPlacedWord]
    publishTime: int | None = None
    publishTimeZone: str | None = None
    #: The series the puzzle was fetched from, set by the client.
    series: str | None = None

    @property
    def published(self) -> datetime.datetime | None:
        return _ms(self.publishTime)

    @property
    def date(self) -> str | None:
        """The publication date in New York."""
        return _eastern_date(self.published)

    @property
    def constructor(self) -> str:
        """The author before "; edited by"."""
        return self.author.split(";")[0].strip()

    @property
    def editor(self) -> str | None:
        match = re.search(r"edited by\s+(.+)$", self.author, re.I)
        return match.group(1).strip() if match else None

    def is_block(self, row: int, col: int) -> bool:
        value = self.box[col][row]
        return value in (None, "", "\x00")

    def grid(self) -> list[list[str | None]]:
        """The solution as rows of letters, None for black squares."""
        return [[None if self.is_block(r, c) else self.box[c][r] for c in range(self.w)]
                for r in range(self.h)]

    def entries(self):
        """Every entry with its clue, answer, squares and crossings."""
        from atlgames.structure import crossword_entries
        return crossword_entries(self)

    def squares(self):
        """Every square: answer, number and whether it's black."""
        from atlgames.structure import crossword_squares
        return crossword_squares(self)


class CrosswordListing(AtlanticModel):
    """A crossword in a series' list (no grid or clues)."""
    puzzleId: str
    title: str = ""
    author: str = ""
    puzzleType: str = "CROSSWORD"
    gridWidth: int | None = None
    gridHeight: int | None = None
    numWords: int | None = None
    publicationTime: int | None = None
    publicationTimeZone: str | None = None
    publicationDateTime: datetime.datetime | None = None
    series: str | None = None

    @property
    def published(self) -> datetime.datetime | None:
        return self.publicationDateTime or _ms(self.publicationTime)

    @property
    def date(self) -> str | None:
        return _eastern_date(self.published)


class CrosswordPlay(AtlanticModel):
    """Your saved play of a crossword, from Amuse Labs.

    Amuse Labs keys plays by your Atlantic user ID, so this is the progress
    the Atlantic's crossword page shows you. `playState` is Amuse Labs'
    code (0 is not started).
    """
    puzzleId: str | None = Field(default=None, alias="id")
    userId: str | None = None
    playId: str | None = None
    series: str | None = None
    playState: int = 0
    score: int | None = None
    timeTaken: int | None = None
    timeOnPage: int | None = None
    nCorrectEntries: int | None = None
    checkUsed: bool | None = None
    revealUsed: bool | None = None
    hintUsed: bool | None = None
    timestamp: int | None = None
    updatedTimestamp: int | None = None
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @property
    def started(self) -> bool:
        return bool(self.playState or self.timeTaken)

    @property
    def updated(self) -> datetime.datetime | None:
        return _ms(self.updatedTimestamp or self.timestamp)


# Rabbithole

def normalize_answer(text: str) -> str:
    """Normalize an answer the way Rabbithole does before comparing:
    accents and punctuation removed, lowercase, single spaces."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", "", text.lower())
    return " ".join(text.split())


def answer_ratio(guess: str, answer: str) -> int:
    """Similarity from 0 to 100 between two normalized answers.

    Rabbithole uses fuzzball's `ratio`; this uses difflib's, which is the
    same measure fuzzywuzzy falls back to, so results can differ slightly
    on borderline guesses.
    """
    a, b = normalize_answer(guess), normalize_answer(answer)
    if not a or not b:
        return 100 if a == b else 0
    return round(100 * difflib.SequenceMatcher(None, a, b).ratio())


class ArticleRef(AtlanticModel):
    """An Atlantic article a game links to."""
    id: str | None = None
    title: str | None = None
    url: str | None = None


class RabbitholeQuestion(AtlanticModel):
    """One question in a Rabbithole chain. Its answer leads to the next."""
    id: str
    questionText: str
    canonicalAnswer: str
    validAnswers: List[str] = []
    targetAccuracy: int = 75
    hintText: str = ""
    #: Two wrong answers, shown with the right one as the last resort.
    choices: List[str] = []

    @property
    def question(self) -> str:
        """The question as plain text."""
        return strip_html(self.questionText)

    @property
    def hint(self) -> str:
        return strip_html(self.hintText)

    def accepts(self, guess: str) -> bool:
        """True if Rabbithole would accept a typed guess."""
        return any(answer_ratio(guess, answer) >= self.targetAccuracy
                   for answer in [self.canonicalAnswer, *self.validAnswers])


class RabbitholePuzzle(AtlanticModel):
    """A Rabbithole puzzle: seven trivia questions, each answer leading to
    the next.

    Scoring: 3 points for a question answered without help, 2 after the
    hint, 1 with multiple choice; 21 at most.
    """
    id: str
    publishedAt: datetime.datetime | None = None
    status: str | None = None
    byline: str = ""
    recirculationBlurb: str = ""
    article: ArticleRef | None = None
    questions: List[RabbitholeQuestion] = []

    @property
    def date(self) -> str | None:
        return _eastern_date(self.publishedAt)

    @property
    def max_score(self) -> int:
        return 3 * len(self.questions)


# Trivia

class TriviaQuestion(AtlanticModel):
    id: str
    questionText: str
    canonicalAnswer: str
    validAnswers: List[str] = []
    hintText: str | None = None
    subtext: str | None = None
    topicText: str = ""
    targetAccuracy: int = 75
    relatedArticle: ArticleRef | None = None

    @property
    def question(self) -> str:
        return strip_html(self.questionText)

    def accepts(self, guess: str) -> bool:
        return any(answer_ratio(guess, answer) >= self.targetAccuracy
                   for answer in [self.canonicalAnswer, *self.validAnswers])


class TriviaArticle(AtlanticModel):
    """A day's Atlantic Trivia (three questions from 2026-03-13; the game
    ended on 2026-08-14). Listings have no `questions`."""
    id: str
    title: str = ""
    url: str | None = None
    datePublished: datetime.datetime | None = None
    questions: List[TriviaQuestion] = []

    @property
    def article_id(self) -> str:
        """The numeric article ID, e.g. "688280"."""
        return self.id.split(":")[-1]

    @property
    def date(self) -> str | None:
        return _eastern_date(self.datePublished)


# Stacks

class StacksPuzzle(AtlanticModel):
    """A Stacks puzzle (the game ended on 2026-08-24)."""
    date: str
    id: int
    wordStrings: List[str]
    blackPos: str
    solution: List[int]
    title: str = ""

    def drops(self) -> list[stacks.Drop]:
        """The solution as drops: which word, in which column, in order."""
        return stacks.decode_solution(self.wordStrings, self.solution)

    def rows(self) -> list[str]:
        """The solved board, top row first."""
        return stacks.simulate(self.blackPos, self.drops())


# Games hub

class Game(AtlanticModel):
    """A game on The Atlantic's games hub."""
    name: str
    slug: str
    description: str | None = None
    shortDescription: str | None = None
    url: str | None = None
    iconUrl: str | None = None
    hasArchive: bool = False
    author: str | None = None
    isFeaturedGame: bool = False


# Saved games

class GameProgress(str, Enum):
    notStarted = "notStarted"
    inProgress = "inProgress"
    complete = "complete"


class GameState(AtlanticModel):
    """A saved game from your Atlantic account.

    This is a snapshot: the server keeps only the latest state of each game,
    and it can go backward (the app's reset button, replays, or a sync bug
    that writes an empty game when a puzzle is opened). `createdAt` is when
    the server first saw the game, which can be long after it was played;
    `updatedAt` is when it was last changed. `fetched_at` is when the client
    read it.
    """
    gameKey: str
    gameSlug: str
    gameDate: str
    gameId: str
    progress: GameProgress
    gameState: Dict[str, Any] | None = None
    updatedAt: float | None = None
    createdAt: datetime.datetime | None = None
    userUUID: str | None = None
    fetched_at: datetime.datetime | None = None

    @property
    def updated(self) -> datetime.datetime | None:
        return _ms(self.updatedAt)

    @property
    def complete(self) -> bool:
        return self.progress == GameProgress.complete


class BracketCityGameData(AtlanticModel):
    """Bracket City's saved game fields."""
    puzzleDate: str | None = None
    displayState: str | None = None
    solvedExpressions: List[str] = []
    totalKeystrokes: int = 0
    minimumKeystrokes: int = 0
    wrongGuesses: int = 0
    wrongGuessList: List[str] = []
    peekedClues: List[Any] = []
    megaPeekedClues: List[Any] = []
    hintModeClues: List[Any] = []
    isComplete: bool = False
    #: Only recorded since about August 2025: None means unknown, not late.
    solvedOnPubDate: bool | None = None


class BracketCityGame(GameState):
    """Your saved Bracket City game for a date."""

    @property
    def data(self) -> BracketCityGameData:
        return BracketCityGameData(**(self.gameState or {}))

    @property
    def efficiency(self) -> float | None:
        """Minimum keystrokes over keystrokes typed, for complete games."""
        data = self.data
        if not self.complete or not data.totalKeystrokes:
            return None
        return data.minimumKeystrokes / data.totalKeystrokes

    def solved_fraction(self, puzzle: BracketCityPuzzle) -> float:
        """How much of the puzzle is solved, as the app's calendar ring shows."""
        total = len(puzzle.solutions)
        return min(1.0, len(self.data.solvedExpressions) / total) if total else 0.0


class RabbitholeGameData(AtlanticModel):
    """Rabbithole's saved game fields. `questionResults` holds
    correct_first_try, correct_with_hint, correct_with_choice or incorrect."""
    currentQuestion: Any = None
    questionResults: List[str] = []
    score: int = 0
    status: str | None = None


class RabbitholeGame(GameState):
    """Your saved Rabbithole game."""

    @property
    def data(self) -> RabbitholeGameData:
        return RabbitholeGameData(**(self.gameState or {}))


STATE_MODELS = {"bracket-city": BracketCityGame, "rabbithole": RabbitholeGame}
