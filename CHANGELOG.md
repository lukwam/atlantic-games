# Changelog

All notable changes to this project. The project follows
[Semantic Versioning](https://semver.org/); while it's below 1.0, minor
versions may include breaking changes.

## Unreleased

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
