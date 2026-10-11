# Changelog

## 0.1.0 (unreleased)

First release.

- **Clients:** `AtlanticGamesClient` and `AsyncAtlanticGamesClient`, sharing every request and parser.
- **Bracket City:** puzzles from 2025-01-01. Includes the clue tree (`clues()`, `render()`, `available()`, `steps()`) and the resolved `solved_text`.
- **The Crossword and Caleb's Inferno:** puzzles from Amuse Labs, back to 2018, with entries, squares and listings. The unscramble re-reads its constants when Amuse Labs changes them.
- **Rabbithole:** puzzles with Rabbithole's fuzzy answer matching.
- **Archives of ended games:** Atlantic Trivia and Stacks, including a Stacks drop simulator.
- **Your data** (with the `atljwt6` cookie):
  - saved Bracket City and Rabbithole games
  - crossword plays from Amuse Labs
  - your account and token expiry
  - computed stats (`atlgames.stats`)
- **Crossword exports:** `.puz`, `.ipuz` and `.xml` (`atlgames.formats`).
- **Extras:**
  - `cli`: the `atlg` command line tool, including terminal play for Bracket City and Rabbithole
  - `mcp`: the `atlg-mcp` MCP server
  - `api`: the `atlgames.api` REST API
