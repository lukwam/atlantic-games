"""atlg play: play Bracket City and Rabbithole in the terminal.

Games are played locally: nothing is saved to your Atlantic account.
"""
import random
from typing import Annotated

import typer
from rich.table import Table
from rich.text import Text

from atlgames.cli.output import console
from atlgames.cli.player import RESULT_ICONS
from atlgames.cli.puzzles import DateArgument
from atlgames.cli.puzzles import RabbitholeArgument
from atlgames.cli.puzzles import bracket_text
from atlgames.cli.puzzles import mark
from atlgames.cli.puzzles import rabbithole_puzzle
from atlgames.cli.state import date_arg
from atlgames.cli.state import state
from atlgames.models import normalize_answer
from atlgames.models import strip_html
from atlgames.views import RABBITHOLE_RESULTS

BRACKET_HELP = """Type an answer to solve any clue you can see. Commands:
  /peek N     show the first letter of clue N's answer
  /reveal N   show clue N's answer and fill it in
  /quit       stop playing (nothing is saved)"""
RABBITHOLE_HELP = """Type your answer. Commands:
  /hint      show the hint (the question is then worth 2 points)
  /choices   pick from three choices (worth 1 point)
  /skip      give up on this question and see the answer
  /quit      stop playing (nothing is saved)"""


class Quit(Exception):
    """The player quit."""


def ask(prompt: str) -> str:
    """Read a line from the player; end of input or /quit stops the game."""
    try:
        text = console.input(prompt).strip()
    except EOFError:
        raise Quit() from None
    if text.lower() in ("/quit", "/q", "/exit"):
        raise Quit()
    return text


def register(app: typer.Typer) -> None:
    """Add the play commands to the root app."""
    play = typer.Typer(help="Play a game here in the terminal. Nothing is saved to your account.",
                       no_args_is_help=True)
    play.command("bracket-city")(play_bracket_city)
    play.command("rabbithole")(play_rabbithole)
    app.add_typer(play, name="play")


def play_bracket_city(
    date: DateArgument = "today",
    resume: Annotated[bool, typer.Option("--resume", help="Start from your saved game (needs cookies; "
                                                         "it's read, never changed).")] = False,
) -> None:
    """Play Bracket City: solve the clues inside the brackets, innermost first."""
    day = date_arg(date, "bracket-city")
    client = state.client()
    puzzle = client.bracket_city(None if date == "today" else day.isoformat())
    solved: set[int] = set()
    if resume:
        game = client.bracket_city_game(puzzle.puzzleDate)
        if game:
            by_text = {c.text: c.index for c in puzzle.clues()}
            solved = {by_text[t] for t in game.data.solvedExpressions if t in by_text}
    wrong = peeks = reveals = 0
    console.print(Text(f"Bracket City {puzzle.puzzleDate}" + (f" by {puzzle.author}" if puzzle.author else ""),
                       style="bold"))
    console.print(Text(BRACKET_HELP, style="dim"))
    total = len(puzzle.clues())
    try:
        while len(solved) < total:
            available = puzzle.available(solved)
            console.print()
            console.print(bracket_text(puzzle.render(solved, mark)))
            console.print()
            t = Table(show_header=False, box=None, padding=(0, 1))
            t.add_column(justify="right", style="bold")
            t.add_column()
            for n, clue in enumerate(available, 1):
                t.add_row(str(n), Text(clue.text, style="cyan"))
            console.print(t)
            console.print(Text(f"{len(solved)} of {total} solved", style="dim"))
            guess = ask("Answer: ")
            if not guess:
                continue
            command, _, arg = guess.partition(" ")
            if command.lower() in ("/peek", "/reveal"):
                if not arg.strip().isdigit() or not 1 <= int(arg) <= len(available):
                    console.print(f"[yellow]Give a clue number from 1 to {len(available)}.[/yellow]")
                    continue
                clue = available[int(arg) - 1]
                if command.lower() == "/peek":
                    peeks += 1
                    console.print(f"[yellow]{clue.answer[0]}{'_' * (len(clue.answer) - 1)}[/yellow]")
                else:
                    reveals += 1
                    solved.add(clue.index)
                    console.print(f"[yellow]{clue.answer}[/yellow]")
                continue
            if command.startswith("/"):
                console.print(Text(BRACKET_HELP, style="dim"))
                continue
            matches = [c for c in available if normalize_answer(c.answer) == normalize_answer(guess)]
            if matches:
                solved.update(c.index for c in matches)
                console.print("[green]✔[/green]")
            else:
                wrong += 1
                console.print("[red]✘ Not one of these clues' answers.[/red]")
    except Quit:
        console.print(f"Stopped with {len(solved)} of {total} clues solved.")
        return
    console.print()
    console.print(bracket_text(mark(puzzle.solved_text)))
    if puzzle.completionText:
        console.print(Text(puzzle.completionText, style="italic"))
    if puzzle.completionURL:
        console.print(Text(puzzle.completionURL, style="dim"))
    console.print()
    console.print(f"[bold green]Solved![/bold green] {wrong} wrong guesses, {peeks} peeks, {reveals} reveals.")


def play_rabbithole(puzzle: RabbitholeArgument = None) -> None:
    """Play Rabbithole: seven questions, each answer leading to the next.

    3 points for an answer without help, 2 after the hint, 1 with multiple
    choice.
    """
    puzzle = rabbithole_puzzle(state.client(), puzzle)
    console.print(Text(f"Rabbithole {puzzle.date}" + (f" by {puzzle.byline}" if puzzle.byline else ""),
                       style="bold"))
    console.print(Text(RABBITHOLE_HELP, style="dim"))
    results: list[str] = []
    try:
        for n, question in enumerate(puzzle.questions, 1):
            results.append(ask_question(n, len(puzzle.questions), question))
    except Quit:
        console.print(f"Stopped after {len(results)} questions.")
    score = sum(RABBITHOLE_RESULTS[r] for r in results)
    console.print()
    console.print(f"[bold]Score: {score} of {puzzle.max_score}[/bold] "
                  + "".join(RESULT_ICONS[r] for r in results))
    if len(results) == len(puzzle.questions):
        if puzzle.recirculationBlurb:
            console.print(Text(strip_html(puzzle.recirculationBlurb), style="italic"))
        if puzzle.article and puzzle.article.url:
            console.print(Text(puzzle.article.url, style="dim"))


def ask_question(number: int, total: int, question) -> str:
    """Ask one question until it's answered, and return its result."""
    console.print()
    console.print(Text.assemble((f"{number}/{total} ", "bold"), question.question))
    result = "correct_first_try"
    while True:
        guess = ask("Answer: ")
        command = guess.lower()
        if not guess:
            continue
        if command == "/hint":
            console.print(Text(question.hint or "No hint for this one.", style="yellow"))
            result = "correct_with_hint"
        elif command == "/choices":
            choices = [question.canonicalAnswer, *question.choices]
            random.shuffle(choices)
            for n, choice in enumerate(choices, 1):
                console.print(f"  [bold]{n}[/bold] {choice}")
            pick = ask("Choice: ")
            if pick.isdigit() and 1 <= int(pick) <= len(choices):
                pick = choices[int(pick) - 1]
            if question.accepts(pick):
                console.print(f"[green]✔ {question.canonicalAnswer}[/green]")
                return "correct_with_choice"
            console.print(f"[red]✘ It was {question.canonicalAnswer}.[/red]")
            return "incorrect"
        elif command == "/skip":
            console.print(f"[red]It was {question.canonicalAnswer}.[/red]")
            return "incorrect"
        elif command.startswith("/"):
            console.print(Text(RABBITHOLE_HELP, style="dim"))
        elif question.accepts(guess):
            console.print(f"[green]✔ {question.canonicalAnswer}[/green]")
            return result
        else:
            console.print("[red]✘ Not quite.[/red] Try again, or /hint, /choices or /skip.")
