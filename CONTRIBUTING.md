# Contributing

Thanks for helping. The Atlantic and Amuse Labs change their games without
notice, so reports of something that stopped working are as valuable as code.

## Reporting a bug

Open an issue with:

- the method or `atlg` command you ran (for example `bracket_city("2026-10-08")`)
- the full error message
- your `atlantic-games` version (`python -c "import atlgames; print(atlgames.__version__)"`)

Never include your `atljwt6` cookie or other cookies in an issue.

## Development setup

```bash
git clone https://github.com/lukwam/atlantic-games.git
cd atlantic-games
python -m venv .venv
source .venv/bin/activate
pip install -e ".[api,cli,mcp,test]"
pytest
```

The tests mock every service, so they run offline and don't need cookies.
Each client test runs against both `AtlanticGamesClient` and
`AsyncAtlanticGamesClient`.

Lint with ruff, which CI also runs, or install the pre-commit hooks to run it
on every commit:

```bash
ruff check
pre-commit install
```

Run the API locally with auto-reload:

```bash
uvicorn atlgames.api:app --reload
```

## Project layout

```
src/atlgames/
    client.py        AtlanticGamesClient and AsyncAtlanticGamesClient: every operation, written once
    transport.py     Requests, retries and error mapping for both clients
    models.py        Pydantic models for the services' responses
    exceptions.py    Error types
    auth.py          Cookie parsing and the account read from the atljwt6 cookie
    amuse.py         Amuse Labs PuzzleMe pages: the crossword's scramble and params
    bracket_city.py  Bracket City's nested clues: render, available clues, solving order
    stacks.py        Stacks puzzles from the game's script, and replaying solutions
    structure.py     Crossword entries and squares
    stats.py         Streaks and totals computed from saved games
    formats.py       Crossword export: .puz, .ipuz and Crossword Compiler .xml
    api.py           Optional FastAPI app and router (the "api" extra)
    views.py         Plain data views of puzzles and saved games, shared by atlg and the MCP server
    mcp_server.py    Optional MCP server for AI agents (the "mcp" extra)
    cli/             Optional atlg command line (the "cli" extra)
        app.py       Root command, global options and error messages
        puzzles.py   Puzzle commands
        play.py      Terminal play for Bracket City and Rabbithole
        player.py    stats, today and history
        archive.py   archive
        settings.py  auth and config commands
        output.py    --format handling, shared by every command
        extension.py Public API for tools built on atlg; keep it backwards compatible
tests/
    fixtures/        Trimmed captures of real responses; saved games and tokens are made up
examples/            Small scripts built on the package, and an example API with a Dockerfile
docs/                endpoints.md: the endpoints, limits and quirks behind each game
```

## How the client works

Each client method is a generator in `_Operations` that yields
`transport.Request`s and receives the decoded responses. `run_sync` and
`run_async` drive the same generator with `httpx.Client` or
`httpx.AsyncClient`, so a new endpoint only has to be written once. Errors
from a request are thrown into the generator, so an operation can catch a
404 and fall back.

Cookies are only sent with requests marked `auth=True`, which are only ever
made to The Atlantic's GraphQL API. Never mark a request to Amuse Labs,
CloudFront or another host as `auth=True`.

## Fixtures

Fixtures are real responses, trimmed to what the tests need. Before adding
one:

- remove cookies, login tokens, user IDs and anything else personal; replace
  saved games and tokens with made-up ones (see `tests/support.py`)
- keep it small: a handful of puzzles, or the part of a script that matters,
  not the whole file

## Checking against the real services

The tests mock everything. To check the real services, run the live tests
(about one request each) or the full live check that runs every morning in
GitHub Actions:

```bash
pytest -m live
python scripts/live_check.py
```

Set `ATLANTIC_COOKIES` to your `atljwt6` cookie to also check your saved games.

## Adding or fixing an endpoint

1. Add an operation to `_Operations` in `client.py`, and a model in
   `models.py`. Models allow extra fields, so only type the fields you use or
   document. Both clients get the method automatically.
2. Add a route to `api.py` that calls the client method, and a command to
   `cli/` if it's useful on the command line. Commands build JSON-compatible
   data and pass it to `output.emit()` with a table renderer, so every output
   format works. Hide answers unless `--answers` is given.
3. Add tests that mock the responses with `respx`, using a trimmed fixture,
   and check the method against the real service before opening a pull
   request.
4. Update the tables in `README.md`, note anything new about the endpoint in
   `docs/endpoints.md`, and add a line to `CHANGELOG.md`.

## Pull requests

Tests run on Python 3.10 to 3.14 for every pull request, plus the next
Python release while it's in pre-release. Keep changes focused, and explain
in the description what you checked against the real services.

## Releases

Maintainers release by bumping `__version__` in `src/atlgames/__init__.py`,
updating `CHANGELOG.md`, and pushing a `vX.Y.Z` tag. The publish workflow
checks the tag matches the version, runs the tests and publishes to TestPyPI,
then PyPI. To try a release first, run the "Publish to PyPI" workflow by hand
(Actions → Run workflow) on your branch: it publishes to
[TestPyPI](https://test.pypi.org/project/atlantic-games/) only, and the tag
skips that version there later.
