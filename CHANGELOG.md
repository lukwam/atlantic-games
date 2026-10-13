# Changelog

All notable changes to this project. The project follows
[Semantic Versioning](https://semver.org/); while it's below 1.0, minor
versions may include breaking changes.

## 0.4.5 (2026-10-12)

### Fixed

- Source distributions include the whole test tree (`tests/__init__.py`,
  `support.py`, `conftest.py` and the fixtures), the scripts the tests load,
  and the docs and contributor files, so an extracted sdist runs its own
  offline tests. CI and the publish workflow check that with
  `scripts/check_sdist.sh`, which builds a wheel from the extracted sdist
  and runs its tests away from the checkout. (#16)
- A server's `Retry-After` was capped at 60 seconds, so a longer wait
  turned into an early retry. The 60-second cap now applies only to the
  client's own exponential backoff. `Retry-After` is honored in full up to
  5 minutes; a longer one raises the error at once, with `retry_after` set,
  instead of retrying early. Non-finite values such as `inf` fall back to
  the backoff. (#14)
- `atlg archive --overwrite` keeps the saved puzzle if writing its update
  fails. It used to move the file into `revisions/` first, so a failed write
  left it missing; now the old file is copied to `revisions/` and replaced
  only once the new one is completely written. `manifest.json` is written
  the same way, so an interrupted run leaves the previous complete manifest.
  A file that's on disk but missing from the manifest, as after an
  interrupted run, is added to the manifest as it is the next time. (#12)
- Saving `config.ini`, which holds your cookies, is atomic. It used to be
  truncated and rewritten in place, so a failed or interrupted save could
  lose your profiles. The new contents go to a private (0600) temporary file
  that replaces the config only once complete, and the config stays 0600
  even if it had been made readable by others. `active_profile` is written
  atomically too. (#17)

## 0.4.4 (2026-10-12)

### Fixed

- The temporary file used to replace a file with `overwrite` is private
  (0600) from the moment it's created. In 0.4.3 it started out readable
  under your umask and was made private just before the data was written,
  so a reader that opened it in that moment could still read the data. A
  new file's permissions now come from an empty file created and removed
  to find what your umask allows. (#8)
- A status in an error from The Atlantic's API must be an HTTP status, as a
  number or three ASCII digits. Strings such as `"²"` or a 5000-digit number
  passed the old digit check but couldn't be converted, so they raised
  `ValueError` and the REST API answered 500; they now raise
  `AtlanticGamesParseError`. (#9)

## 0.4.3 (2026-10-12)

### Fixed

- When a crossword export or `atlg ... --save` replaced a file with
  `overwrite`, the new content sat in a temporary file readable under your
  umask (often 0644) until it was moved into place, even when the file being
  replaced was private. The temporary file is now private (0600) while it
  holds the data; the final file's permissions are unchanged. (#8)
- Malformed metadata in an error from The Atlantic's API, such as a status
  or error code of the wrong type, raises `AtlanticGamesParseError` instead
  of `AttributeError` or `TypeError`, so the REST API answers 502 instead of
  500. (#9)

## 0.4.2 (2026-10-12)

### Fixed

- `AtlanticGamesParseError` messages no longer include dictionary keys taken
  from the response, which could be private too. Field paths keep the
  models' own field names and list indexes, and show anything else as `*`,
  as in `solutions.*: string_type`. (#3)
- `AtlanticGamesGraphQLError` and the other errors from The Atlantic's API
  no longer include its error messages, which can echo the request or its
  data; they name the standard GraphQL error codes and HTTP statuses
  instead. The messages are still in the exception's `errors`. (#3)
- Malformed responses from The Atlantic's API, such as a missing `data` or
  operation, raise `AtlanticGamesParseError` instead of `TypeError` or
  `KeyError`, so the REST API answers 502 instead of 500. (#3)
- A crossword exported with `overwrite` (or saved with `atlg ... --save`) to
  a new file got 0644 permissions even under a stricter umask, such as 077.
  New files now get the permissions your umask allows with or without
  `overwrite`, and a replaced file keeps its own. (#4)

## 0.4.1 (2026-10-12)

### Fixed

- The package installs `tzdata` on every platform. Without a system time
  zone database (Windows, slim containers), `import atlgames` failed with
  `ZoneInfoNotFoundError`. CI now installs the package alone and each extra
  alone, on Linux and Windows, and checks New York time without a system
  database. (#5)
- The MCP server's `export_crossword` never replaces a file unless
  `overwrite` is set. It checked for the file before fetching the puzzle, so
  a file created in the meantime was overwritten anyway; the file is now
  created exclusively, and symlinks are never followed. With `overwrite`,
  the new file is written next to the old one and moved into place, so a
  failed write keeps the old file. `atlg ... --save` replaces files the same
  way. (#4)
- `export_crossword` is marked destructive in its MCP annotations, since
  `overwrite` replaces files. (#4)
- A response that's valid JSON but the wrong shape raises
  `AtlanticGamesParseError`, as documented. It used to escape as Pydantic's
  `ValidationError` or a `TypeError`, so the REST API answered 500 instead
  of 502. If you caught those, catch `AtlanticGamesParseError` (a
  `ValueError`) instead. (#3)
- Errors never include the response's values, which can be your saved
  games. `AtlanticGamesParseError` names the model, fields and error types
  only; the models hide input values in validation errors; and the MCP
  server, CLI and live check report these errors without them. The live
  check reports other unexpected errors by type and location only, since its
  failures are published in GitHub issues. (#3)

## 0.4.0 (2026-10-12)

### Changed

- The MCP server builds every response from `atlgames.views`, as in
  nytimes-games, so `atlg-mcp` and `atlg --format json` return the same
  fields. This changes the MCP tools' responses: puzzle and article IDs are
  `id` (not `puzzle_id` or `article`), Bracket City clues are numbered from
  1 like Rabbithole and Trivia questions, the crossword's author is
  `constructor`, Stacks columns are numbered from 1, and history tools list
  dates without a saved game as not played.
- `atlg --format json` output: Bracket City's clue count is `clue_count` and
  its clue list `clues`; Rabbithole's question count is `question_count`,
  and its questions are always `questions` (only the first, without
  `--answers`), with the multiple choice options including the answer.
  Crossword and Trivia titles, and game descriptions, have HTML removed.
  `atlg stats` reports the first and last completed dates instead of the
  full list, as the MCP server does.

## 0.3.0 (2026-10-12)

### Changed

- `atlgames.views` (formerly the internal `atlgames.cli.views`) is now at the
  package level, as in nytimes-games.
- Linted with ruff, in CI and as a pre-commit hook.

## 0.2.0 (2026-10-11)

### Added

- `GameState.advancement`, `better_than()` and `solved` compare snapshots of
  the same game, so you can keep the best state you've seen (complete > in
  progress > not started, then more solved; ties keep the earliest finish,
  or the latest save for unfinished games).
- `atlgames.cli.extension`, a stable public API for building your own
  command line on `atlg`: `create_app`, `run`, `FormatOption`, `emit`,
  `key_value_table`, `get_client` and more.
- A read-only guarantee: GraphQL mutations are refused before any request,
  the README documents that the library never writes, and the tests check
  that every request is a GET.

## 0.1.0 (2026-10-11)

First release.

### Added

- `AtlanticGamesClient` and `AsyncAtlanticGamesClient`, sharing every
  request and parser.
- Bracket City puzzles from 2025-01-01, with the clue tree (`clues()`,
  `render()`, `available()`, `steps()`) and the resolved `solved_text`.
- The Crossword and Caleb's Inferno from Amuse Labs, back to 2018, with
  entries, squares and listings. The unscramble re-reads its constants when
  Amuse Labs changes them.
- Rabbithole puzzles, with Rabbithole's fuzzy answer matching.
- The archives of the ended games, Atlantic Trivia and Stacks, including a
  Stacks drop simulator.
- Your data, with the `atljwt6` cookie: saved Bracket City and Rabbithole
  games, crossword plays from Amuse Labs, your account and token expiry, and
  computed stats (`atlgames.stats`).
- Crossword exports to `.puz`, `.ipuz` and `.xml` (`atlgames.formats`).
- The `cli` extra (the `atlg` command line tool, including terminal play for
  Bracket City and Rabbithole), the `mcp` extra (the `atlg-mcp` MCP server)
  and the `api` extra (the `atlgames.api` REST API).
