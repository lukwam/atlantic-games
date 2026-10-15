"""Generate docs/screenshot.svg for the README.

Runs a few atlg commands with colors and saves the output with Rich's SVG
export. Uses puzzles from mid-2025 so the screenshot doesn't spoil recent
games, and no commands that show personal data.

    pip install -e ".[cli]"
    python docs/make_screenshot.py
"""
import os
import shlex
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text

COMMANDS = [
    "atlg bracket-city 2025-06-12",
    "atlg crossword 2025-06-12 --answers --no-clues",
    "atlg stacks 2025-06-17 --answers",
]
WIDTH = 92
OUTPUT = Path(__file__).with_name("screenshot.svg")


def main() -> None:
    env = {**os.environ, "FORCE_COLOR": "1", "COLUMNS": str(WIDTH), "TERM": "xterm-256color"}
    env.pop("ATLANTIC_COOKIES", None)
    console = Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor",
                      file=open(os.devnull, "w"))
    for i, command in enumerate(COMMANDS):
        if i:
            console.print()
        console.print(Text.assemble(("$ ", "bold green"), (command, "bold")))
        args = shlex.split(command)
        result = subprocess.run([sys.executable, "-m", "atlgames.cli", *args[1:]],
                                capture_output=True, text=True, env=env, check=True)
        console.print(Text.from_ansi(result.stdout.rstrip("\n")))
    console.save_svg(str(OUTPUT), title="atlg")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
