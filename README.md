# atlantic-games

[![PyPI](https://img.shields.io/pypi/v/atlantic-games)](https://pypi.org/project/atlantic-games/)
[![Python](https://img.shields.io/pypi/pyversions/atlantic-games)](https://pypi.org/project/atlantic-games/)
[![Test](https://github.com/lukwam/atlantic-games/actions/workflows/test.yml/badge.svg)](https://github.com/lukwam/atlantic-games/actions/workflows/test.yml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Flukwam%2Fatlantic-games%2Fbadges%2Fcoverage-badge.json)](https://github.com/lukwam/atlantic-games/actions/workflows/test.yml)
[![Atlantic live check](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Flukwam%2Fatlantic-games%2Fbadges%2Flive-check.json)](https://github.com/lukwam/atlantic-games/actions/workflows/live.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/lukwam/atlantic-games/blob/main/LICENSE)

An unofficial Python client for The Atlantic's games: Bracket City, the
Crossword, Caleb's Inferno and Rabbithole, plus the archives of Atlantic
Trivia and Stacks, and your own saved games and stats.

The Atlantic doesn't publish documentation for these. This package wraps
them in one client, sync and async, with typed
[Pydantic](https://docs.pydantic.dev/) models. Optional extras add the `atlg`
command line tool, an MCP server for AI agents, and a REST API. It's the
sibling of [nytimes-games](https://github.com/lukwam/nytimes-games) and works
the same way.

The crosswords are hosted by [Amuse Labs](https://amuselabs.com)' PuzzleMe,
which does a great job of putting puzzles in front of more people on more
sites. Thanks to them.

## Installation

```bash
pip install atlantic-games
```

The package installs as `atlantic-games` and is imported as `atlgames`.
Python 3.10 or newer is required.

## Quick start

```python
from atlgames import AtlanticGamesClient

client = AtlanticGamesClient()

client.bracket_city("2026-10-08").solved_text   # "Raytheon patents the microwave"
client.crossword("2026-10-10").entries()         # clues, answers, crossings
client.crossword(series="inferno")               # the latest Caleb's Inferno
client.rabbithole().questions                    # the latest Rabbithole chain
```

The async client has the same methods:

```python
from atlgames import AsyncAtlanticGamesClient

async with AsyncAtlanticGamesClient() as client:
    puzzle = await client.bracket_city()
```

Your saved games need your Atlantic login cookie:

```python
from atlgames.stats import bracket_city_stats

client = AtlanticGamesClient(cookies="atljwt6=...")

client.bracket_city_game("2026-10-11").data.totalKeystrokes
bracket_city_stats(client.bracket_city_games()).longest_streak
```

## What's available

Puzzles don't need cookies. Everything about you does.

### Puzzles

| Game | Methods | Available | Spoilers |
|---|---|---|---|
| Bracket City | `bracket_city(date=None)`, `bracket_city_dates()` | 2025-01-01, daily | `solutions`, `solved_text` |
| Crossword | `crossword(date=None, puzzle_id=None)`, `crosswords(date_start, date_end, limit)` | 2018-09-24, daily | the grid (`box`) and `placedWords` answers |
| Caleb's Inferno | the same, with `series="inferno"` | 2022 to 2026-06, monthly | as for the Crossword |
| Rabbithole | `rabbithole(puzzle_id=None)`, `rabbithole_puzzles(date_start, date_end)` | 2026-08-12, weekdays | `canonicalAnswer`, `validAnswers` |
| Atlantic Trivia | `trivia(article)`, `trivia_articles(limit)` | 2025-10-03 to 2026-08-14 (ended) | answers, hints and explanations |
| Stacks | `stacks(date)`, `stacks_puzzles()` | 2025-06-17 to 2026-08-24 (ended) | `solution` |
| Games hub | `games()`, `game(slug)` | | |

Dates are `YYYY-MM-DD` strings (or `datetime.date`) in New York time, which
is when the puzzles change. With no date you get the latest puzzle.
Unpublished puzzles aren't available early.

### You (needs your `atljwt6` cookie)

| Data | Method | What you get |
|---|---|---|
| Account | `client.account` | Your user ID, when your login expires and your subscription flags, read from the cookies (no request) |
| Bracket City | `bracket_city_game(date)`, `bracket_city_games(date_start, date_end)` | Solved clues, keystrokes against the minimum, wrong guesses, peeks, whether you solved it on the day |
| Rabbithole | `rabbithole_game(puzzle)`, `rabbithole_games(date_start, date_end)` | Each question's result and your score |
| Crossword | `crossword_play(puzzle_id, series)` | Your saved play from Amuse Labs: time, score, correct entries, checks and reveals |
| Any game | `game_state(slug, date, id)`, `game_states(keys)` | The raw saved game, 25 per request |
| Stats | `atlgames.stats.bracket_city_stats(games)`, `rabbithole_stats(games)` | Streaks, completion, keystroke efficiency, perfect and clean solves, scores |

The Atlantic has no stats endpoint, so stats are computed from your saved
games. Some things to know about saved games:

- **Old games may not be there yet.** The mobile app keeps your history on
  the phone and only uploads a puzzle when you open it while logged in. Open
  old dates in the app to bring them into your account.
- **They're snapshots.** The server keeps only the latest state of each game,
  and it can go backward: the app's "reset puzzle" button, replaying, or
  opening a date can replace a finished game with an empty one. Each result
  has `fetched_at`; keep your own copies if your history matters to you.
- `solvedOnPubDate` was only recorded from about August 2025, so None means
  unknown, not late.

To keep the best state you've seen, compare snapshots of the same game:

```python
best = stored if stored.better_than(fetched) else fetched
best = max(snapshots, key=lambda game: game.advancement)
```

`advancement` ranks complete above in progress above not started, then more
solved (Bracket City clues, Rabbithole questions answered). Ties between
finished games go to the earliest completion, since a replay is usually
faster and wasn't played on the day; ties between unfinished games go to the
latest save.

### Read-only

The library never writes anything to The Atlantic or Amuse Labs. Every
request it makes is a GET; it never sends GraphQL mutations (`saveGameState`
is refused before any request is made) and never posts plays to Amuse Labs.
`crossword_play` only loads the crossword's page, as a browser would, to
read your saved play; Amuse Labs may record that page load, but it doesn't
change your play. The test suite checks that every request is a GET.

### Puzzle structure

```python
puzzle = client.bracket_city("2026-10-11")

puzzle.clues()          # every clue: its text, answer, depth and the clues inside it
puzzle.available()      # the clues you can solve now
puzzle.render(["your + my", "ghost's exclamation"])   # the text with those clues solved
puzzle.steps()          # an order that solves it, innermost first
puzzle.solved_text      # the final text the game shows
puzzle.caption_matches  # False for the ~1 in 30 puzzles whose puzzleSolution differs

crossword = client.crossword("2026-10-10")
crossword.grid()        # rows of letters, None for black squares
crossword.entries()     # "1-Across": clue, answer, (row, col) squares, crossings
crossword.squares()

question = client.rabbithole().questions[0]
question.accepts("mark zuckerburg")   # Rabbithole's fuzzy answer matching

client.stacks("2025-06-17").rows()    # the solved Stacks board
```

### Crossword files

Export crosswords to the formats other crossword apps use:

```python
from atlgames import formats

puzzle = client.crossword("2026-10-10")
open("atlantic.puz", "wb").write(formats.to_puz(puzzle))   # Across Lite
formats.to_ipuz(puzzle)                                     # ipuz, as a dict
formats.to_xml(puzzle)                                      # Crossword Compiler XML
formats.export(puzzle, "ipuz")                              # any format, as bytes
formats.fidelity(puzzle, "puz")                             # what the format approximates
```

Clue formatting such as italics is dropped. Puzzles a format can't represent
raise `AtlanticGamesExportError` with the reasons. Exported files are for
personal use: the puzzles are The Atlantic's.

## Cookies

Log in at theatlantic.com, open your browser's developer tools, and copy the
`atljwt6` cookie for `.theatlantic.com` (Application tab in Chrome, Storage
tab in Firefox). It's httpOnly, so scripts on the page can't read it. Treat it
like a password. It lasts 30 days; the site renews it as you browse, so you'll
need to copy a fresh one about once a month.

`cookies` can be a `Cookie` header string, a dict, a Cookie-Editor JSON
export (as a list or a JSON string), or the bare `atljwt6` token. Only
`atljwt6` is needed; `atljwt` adds your subscription flags to `account`.

Cookies are only ever sent to The Atlantic's API, never to Amuse Labs or the
puzzle file servers, and they never appear in errors or logs.

Your crossword progress is stored by Amuse Labs under your Atlantic user ID.
That ID is read from your own cookie; the client has no way to ask for anyone
else's.

## Errors

| Exception | When |
|---|---|
| `AtlanticGamesNotFoundError` | No puzzle for that date or ID, or not published yet |
| `AtlanticGamesAuthenticationError` | Your data was requested without a valid `atljwt6` cookie |
| `AtlanticGamesRateLimitError` | 429 after retrying; `retry_after` has the suggested wait |
| `AtlanticGamesGraphQLError` | The Atlantic's API returned other errors |
| `AtlanticGamesHTTPError` | Any other HTTP error (the base of the above) |
| `AtlanticGamesParseError` | A response or page wasn't in the expected format, e.g. Amuse Labs changed its format; the message names the fields, never their values |
| `AtlanticGamesExportError` | A crossword can't be saved in a file format |

```python
from atlgames import AtlanticGamesNotFoundError

try:
    client.bracket_city("1900-01-01")
except AtlanticGamesNotFoundError:
    print("No puzzle that day")
```

### Network behavior

Failed connections, rate limits and server errors are retried 3 times with
exponential backoff (up to 60 seconds between tries). Adjust with
`AtlanticGamesClient(retries=5, backoff=1.0, timeout=60)`, or turn retries off
with `retries=0`.

A server's `Retry-After` is always honored: the client waits as long as it
asks, up to 5 minutes. If it asks for longer, the client doesn't retry early;
it raises the error at once, and `AtlanticGamesRateLimitError.retry_after`
says how many seconds to wait.

You can pass your own `httpx.Client` (or `httpx.AsyncClient` for the async
client) as `http_client`, for example to add caching or a proxy. The client
doesn't close it.

Cookies are sent only to The Atlantic's API and are never logged.

## Models

Every method returns Pydantic models from `atlgames.models`. Fields The
Atlantic or Amuse Labs add later are kept rather than rejected, so new fields
don't break your code. Use `.model_dump()` to get plain dicts.

## Examples

[`examples/`](examples) has small projects built on the package: the
[most deeply nested](examples/bracket_city_depth.py) Bracket City puzzles,
[clue reuse](examples/clue_reuse.py) across recent crosswords, your Bracket
City [keystroke efficiency](examples/bracket_city_efficiency.py) by weekday,
and [your own REST API](examples/api) in Docker.

## Async apps

`AsyncAtlanticGamesClient` has every method of `AtlanticGamesClient`,
awaited. Both use [httpx](https://www.python-httpx.org/), so there's no extra
to install:

```python
import asyncio
from atlgames import AsyncAtlanticGamesClient


async def main():
    async with AsyncAtlanticGamesClient(cookies="atljwt6=...") as client:
        puzzle = await client.bracket_city()
        games = await client.bracket_city_games("2026-10-01")
        # Fetch several at once; keep it modest to be polite to The Atlantic.
        week = await asyncio.gather(*(client.bracket_city(f"2026-10-0{d}") for d in range(1, 8)))


asyncio.run(main())
```

Errors, retries and cookie handling are the same as the sync client's. Pass
your own `httpx.AsyncClient` as `http_client` to control transport details;
it isn't closed when the client is. Both clients run the same code for every
endpoint, so they always have the same methods.

**FastAPI:** use `AsyncAtlanticGamesClient` in `async def` routes, or the sync
client in plain `def` routes (FastAPI runs those in a thread pool). The
routes in `atlgames.api` use the async client.

## Command line

The `cli` extra installs `atlg`:

```bash
pip install "atlantic-games[cli]"

atlg bracket-city              # today's puzzle, no spoilers
atlg bracket-city 2026-10-08 --steps -a
atlg crossword yesterday --save crossword.puz
atlg crossword --series inferno
atlg rabbithole -a
atlg trivia last
atlg stacks 2025-06-17 -a
atlg list crossword --from 2026-10-01
atlg play bracket-city         # play in the terminal (nothing is saved to your account)
atlg play rabbithole
```

Answers are hidden unless you pass `--answers` / `-a`. Every command takes
`--format json|yaml|csv|table|value(FIELD,...)`, and dates can be
`YYYY-MM-DD`, `today`, `yesterday`, a weekday name, `first` or `last`.

### Your stats and history

```bash
atlg auth login --from-file cookies.json   # a Cookie-Editor export, or paste atljwt6 when prompted
atlg auth status
atlg today
atlg stats
atlg history bracket-city --from 2026-01-01
```

Cookies are read from `--cookies`, then the `ATLANTIC_COOKIES` environment
variable, then the active profile (see [Profiles and settings](#profiles-and-settings)).

### Archiving

```bash
atlg archive bracket-city --from first --to today -o archive
atlg archive crossword --from 2026-01-01 -o archive --as puz
```

Archives write one file per date with a manifest, and resume where they
left off.

### Output formats

Every command takes `--format` (`-f`), like gcloud:

| Format | Output |
|---|---|
| `table` | Tables and grids (the default) |
| `json`, `yaml` | All the data |
| `csv` | One row per item, nested fields as dotted columns |
| `value(FIELD,...)` | Tab separated values for scripts, e.g. `value(date,clues,depth)` |

```bash
atlg bracket-city 2026-10-08 -f "value(date,clues,depth)"
atlg stats -f json | jq .
```

### Profiles and settings

Settings are saved per profile in `~/.config/atlg/config.ini`, similar to
gcloud configurations. On Linux and macOS the file is readable only by you
(0600, in a 0700 folder); on Windows it relies on your user folder's
permissions. Saves are atomic, so an interrupted save keeps the previous
settings:

```bash
atlg config set format json      # default output format for this profile
atlg config list
atlg --profile alice auth login  # a second Atlantic account
atlg config profiles activate alice
atlg config profiles list
```

`--profile` or `ATLG_PROFILE` picks a profile for one command. Run
`atlg --install-completion` for shell completion.

### Building your own command line

`atlgames.cli.extension` lets you build a command line with every `atlg`
command plus your own, sharing its root options (`--profile`, `--cookies`,
`--format`), output formats and error messages:

```python
import typer
from atlgames.cli.extension import FormatOption, create_app, emit, get_client, run

app = create_app(name="mytool", help="My Atlantic tools.", version="1.0.0")
sync = typer.Typer(help="Sync my games.")
app.add_typer(sync, name="sync")


@sync.command("bracket-city")
def sync_bracket_city(fmt: FormatOption = None) -> None:
    """My October Bracket City games."""
    games = get_client().bracket_city_games("2026-10-01", "2026-10-31")
    emit([{"date": g.gameDate, "progress": g.progress.value} for g in games], fmt)


def main() -> None:   # point your [project.scripts] entry here
    run(app)
```

Each `create_app()` call returns an independent app. `emit(data, fmt,
table)` prints JSON-compatible data in the requested format, with an optional
function that renders the table format, and `key_value_table()` builds a
two-column table. `get_client()` returns a client with the cookies `atlg`
would use; `resolve_cookies()`, `active_profile()`, `get_setting()` and
`parse_date()` are there too. The other modules in `atlgames.cli` are
internal.

## MCP server for AI agents

The `mcp` extra installs `atlg-mcp`, a local
[Model Context Protocol](https://modelcontextprotocol.io) server, so agents
can play along: ask for a Bracket City nudge, check a Rabbithole answer, or
export today's crossword.

```bash
# Claude Code
claude mcp add atlantic-games -- uvx --from "atlantic-games[mcp]" atlg-mcp
```

For other clients, add a stdio server with the command `uvx` and the
arguments `--from atlantic-games[mcp] atlg-mcp`.

| Tools | What they do |
|---|---|
| `bracket_city`, `bracket_city_peek`, `check_bracket_city_answer` | The puzzle with the clues you can solve now, peeks, and answer checks |
| `crossword`, `check_crossword_answer`, `crossword_archive` | Grids and entries with clues, lengths and crossings |
| `rabbithole`, `check_rabbithole_answer`, `rabbithole_archive` | One question at a time, with hints and choices on request |
| `trivia`, `check_trivia_answer`, `trivia_archive`, `stacks`, `games` | The Trivia and Stacks archives, and the games hub |
| `account`, `bracket_city_history`, `bracket_city_stats`, `rabbithole_history`, `rabbithole_stats`, `crossword_progress` | Your data (need cookies) |
| `export_crossword` | Save a crossword as `.puz`, `.ipuz` or `.xml` |

- Answers are hidden unless the agent asks for them, and the server tells
  agents to leave them hidden while you're solving.
- Your data uses the same login as `atlg` (`atlg auth login`, or
  `ATLANTIC_COOKIES` in the server's environment).
- Every tool is read-only except `export_crossword`, which only writes the
  file you ask for.

## REST API

The `api` extra adds `atlgames.api`, a FastAPI app with every puzzle, your
saved games and stats, and crossword downloads:

```bash
pip install "atlantic-games[api]"
uvicorn atlgames.api:app
```

Open `/docs` for the full list. A few routes:

| Route | Returns |
|---|---|
| `GET /bracket-city/{date}` | A Bracket City puzzle |
| `GET /crosswords/{daily\|inferno}/{date}` | A crossword |
| `GET /crosswords/{series}/{date}/download?format=puz` | A crossword file |
| `GET /rabbithole/latest` | The latest Rabbithole |
| `GET /bracket-city/stats` | Your stats (send your `atljwt6` cookie) |

Requests use the `atljwt6` and `atljwt` cookies they're sent with; no other
cookies are passed on. Mount `atlgames.api.router` in your own app, or start
from [`examples/api`](examples/api) for a Docker container.

## How it works

The Atlantic's games come from four places, none of which need a login for
puzzles:

- **Bracket City** puzzles are JSON files on CloudFront.
- **Crosswords** come from Amuse Labs' PuzzleMe pages. Their puzzle data is
  lightly scrambled; the client unscrambles it and, if Amuse Labs changes
  the scramble, reads the new one from their current JavaScript.
- **Rabbithole, Trivia, the games hub and your saved games** come from The
  Atlantic's GraphQL API.
- **Stacks** ended, and all its puzzles ship inside the game's own script.

[docs/endpoints.md](docs/endpoints.md) has the details: endpoints, schemas and quirks.

## Staying current with The Atlantic

The Atlantic and Amuse Labs change these services without notice. Every
morning a [live check](https://github.com/lukwam/atlantic-games/actions/workflows/live.yml)
fetches a real puzzle from every game and runs the live tests. The **Atlantic
live check** badge above shows the latest result and date, and failures open
an issue automatically.

## Contributing

The Atlantic and Amuse Labs change these services without notice, so bug
reports with the failing date and error are very welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) to set up a development environment.

## License

MIT. This project isn't affiliated with The Atlantic or Amuse Labs. The
puzzles belong to The Atlantic and their constructors.
