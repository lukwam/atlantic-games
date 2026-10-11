# How The Atlantic's games work

Notes on the services behind The Atlantic's games, for contributors and
anyone curious. None of them are documented, so this is what they're
observed to do (as of October 2026) and may change. Where something is
inferred from the games' code rather than seen in responses, it says so.

`www.theatlantic.com` often blocks requests from data centers, but none of
the hosts below are behind that block.

## Sources

| Game | Status | Source | Archive | Answers in the data |
|---|---|---|---|---|
| Bracket City | daily | CloudFront JSON | 2025-01-01 on | yes |
| Crossword | daily | Amuse Labs PuzzleMe, series `atlantic` | 2018-09-24 on | yes |
| Caleb's Inferno | monthly; none listed after June 2026 | Amuse Labs, series `atlantic-inferno` | 2022 to 2026-06 | yes |
| Rabbithole | weekdays | GraphQL | 2026-08-12 on | yes |
| Atlantic Trivia | ended 2026-08-14 | GraphQL | 2025-10 to 2026-08-14 | yes (structured from 2026-03-13) |
| Stacks | ended 2026-08-24 | the game's own script | 2025-06-17 to 2026-08-24 | yes |

Two other games aren't covered. Fluxis ended around July 2026 and its app
and puzzles are gone. The Lemony Snicket mystery is a one-off,
conversation-based game with no puzzle data to fetch.

## GraphQL: `https://graphql.theatlantic.com/`

- **Requests:** GET with `query` (and `variables`) parameters works.
- **API key:** every request needs the public key the games' own pages use,
  `x-api-key: JakhyMEXwa9odtB8gBxFI63ITyKqDGkn7ciGVIJf`. Without it the API
  answers 403.
- **Game queries:**
  - `gamesHub`, `game(slug)`
  - `bracketCityPuzzles(limit, startDate)`
  - `rabbitholePuzzle(id, preview)`, `rabbitholePuzzles(page, pageSize, startDate, endDate)`
  - `amuseLabsPuzzles(series, puzzleId, from, to, limit, offset)`: crossword metadata, no grid. `from` and `to` need full timestamps.
  - `collection(slug, type)`, `article(id)`: used for Trivia
  - `gameState`, `batchGameStates`: your saved games (see below)
- **Errors** carry the status of the service behind them. A missing game or
  puzzle has `extensions.response.status` 404. An unauthenticated request for
  your data answers "Bad request" with `extensions.http.status` 400.

## Bracket City

- `GET https://d2gknrezp32xyk.cloudfront.net/puzzles/YYYY-MM-DD.json` returns a puzzle.
- `GET .../puzzles/index.json` lists every published date.
- Unpublished dates return 403.
- **Fields:**
  - `puzzleDate`, `author`
  - `initialPuzzle`: the sentence with nested `[clues]`
  - `solutions`: `{clue text: answer}`
  - `puzzleSolution`
  - `completionText`, `completionURL`: an "on this day" date and a link
- **How the clues nest:** `solutions` is keyed by each clue's text *after*
  the clues inside it are replaced by their answers. Replacing the innermost
  `[...]` with its answer, again and again, solves every puzzle.
- **The caption can differ:** `puzzleSolution` is an editorial caption. In
  about 1 in 30 puzzles it differs from the resolved text (spacing, wording,
  typos), so the library uses the resolved text (`solved_text`).
- **Older puzzles:** those from before The Atlantic (bracket.city, 2024)
  aren't in this archive.

## Crosswords (Amuse Labs)

- **List:** `GET https://cdn3.amuselabs.com/atlantic/api/v1/puzzles?loadToken=<jwt>&series=<series>&limit=500&offset=N`
  - Returns newest first, with `hasMore`.
  - The anonymous `loadToken` comes from `GET /atlantic/date-picker?set=atlantic`, in the base64 JSON `params.rawsps`.
  - A stale token answers `errorCode` 84.
- **Puzzle:** `GET https://cdn3.amuselabs.com/atlantic/crossword?id=<puzzleId>&set=<series>`
  - Returns HTML with a `<script id="params">` JSON block. `rawc` is the puzzle: base64 JSON, scrambled by reversing fixed-length runs of characters.
  - The run lengths are in Amuse Labs' versioned `/atlantic/<resourceVersionDir>/js/c-min.js`. The library re-reads them from there if the known ones stop working.
  - Unknown or unpublished puzzles still return HTTP 200, as a page titled "PuzzleMe Error".
- **Puzzle fields:**
  - `box`: column-major `box[x][y]`; `"\u0000"` is a black square; the letters are the solution
  - `placedWords[]`: answer, clue, `x`/`y`, direction
  - `clueNums`
  - `title`, `author` ("Name; edited by Editor"), `publishTime`
  - optional `cellInfos` for circles and shading
- **Puzzle IDs are irregular:** `atlantic_YYYYMMDD`, eight-character hex IDs
  from 2018, typo prefixes such as `atlantiv_`, `inferno_YYYYMMDD`. Find them
  through the list rather than building them from dates.
- **Inferno list quirk:** the Inferno series also lists a regular crossword
  (`atlantic_20260614`, "America 250").
- **Your progress:** Amuse Labs keeps crossword plays by user. The Atlantic's
  crossword page identifies you by your Atlantic user ID (the `uid`
  parameter), and the page's `rawp` (base64 JSON) holds your play: `playState`,
  `score`, `timeTaken`, `nCorrectEntries`, `checkUsed`, `revealUsed`,
  `hintUsed` and timestamps.

## Rabbithole

- **Fetching:** `rabbitholePuzzles(page, pageSize)` (newest first), or
  `rabbitholePuzzle(id)`. IDs aren't in date order.
- **Questions:** each puzzle has seven, and each answer leads into the next.
  - `questionText` is HTML; `<strong>` marks what's asked.
  - The rest: `canonicalAnswer`, `validAnswers`, `hintText`, two wrong `choices`, `targetAccuracy` (75).
- **Answer matching** (from the game's code): the guess is normalized
  (accents and punctuation removed, lowercase). It's right if its fuzzy
  `ratio` with the canonical answer or any valid answer is at least
  `targetAccuracy`.
- **Scoring:** 3 points without help, 2 after the hint, 1 with multiple
  choice; 21 at most.

## Atlantic Trivia

- **List:** `collection(slug:"atlantic-trivia", type:"category") { river(first, after) }`.
  - The river rejects more than about 40 per page.
  - It fails if `after` is sent as null, so leave it out on the first page.
- **Questions:** `article(id) { content { ... on ArticleInlineTrivia { questions { ... } } } }`.
- **Two eras:**
  - From 2026-03-13 there are three structured questions a day, each with answers, a hint, a topic and an explanation.
  - Earlier weekly newsletter roundups only have prose.

## Stacks

- **Getting the puzzles:**
  1. `GET https://stacks.games.theatlantic.com/?view=tnf` names the current `/_next/static/chunks/app/page-<hash>.js`.
  2. That script contains every puzzle in a `JSON.parse('[{"wordStrings"…]')`.
- **Fields:** `{wordStrings, blackPos, solution, id, title}`.
  - `blackPos` is the base row, with `-` for empty columns.
  - Each `solution` step is `wordIndex * 10 + column`.
- **Dates:** the puzzle for a date is the one at position `days since 2025-06-17` in the list, not the one with that `id`.
- **Rules:** each letter falls down its own column. In a solved board every
  row except the top one is a word.

## Logging in and saved games

- **The login cookie:** `atljwt6` on `.theatlantic.com`, sent to the GraphQL
  API with the public key, is all that's needed.
  - It's an httpOnly RS256 JWT.
  - Claims: `uuid`/`user_uuid`, `exp` (30 days), `refresh_exp` (a year), `token_type: "sliding"`.
  - The site renews it while you browse. *Inferred:* exactly how isn't known.
  - It isn't renewed by GraphQL requests (they never set cookies), and the
    sites' JavaScript has no refresh call. The accounts API
    (`accounts-api.theatlantic.com/api/v2.0/`) only has `auth/login/`,
    `auth/logout/`, `auth/authorize-email/` and `user/`.
  - Renewal most likely happens on `www.theatlantic.com` page loads, which
    block data-center IPs. So a server can't keep a stored token alive, and
    stored logins need a fresh `atljwt6` about monthly.
- **The entitlements cookie:** `atljwt` (not httpOnly) carries `premium_access`, `paymeter_access`, `ad_free` and `staff`.
- **Saved games:** `batchGameStates(items: [{gameSlug, gameDate, gameId}])`
  returns `{items, unprocessedKeys}` (a DynamoDB-style batch). Up to 25 keys
  per request works.
- **Item fields:** `{userUUID, gameKey, gameSlug, gameDate, gameId, progress, gameState, updatedAt, createdAt}`.
  - `progress` is `notStarted`, `inProgress` or `complete`.
- **Keys by game:**
  - Bracket City: `("bracket-city", date, "v1")`
  - Rabbithole: `("rabbithole", publish date, puzzle id)`
- **Bracket City's `gameState`:**
  - progress: `solvedExpressions` (clue texts), `isComplete`
  - scoring: `totalKeystrokes`, `minimumKeystrokes`, `wrongGuesses`, `wrongGuessList`, `peekedClues`, `megaPeekedClues`, `hintModeClues`
  - display: `displayState`, `initialPuzzle`, `puzzleDate`
  - `solvedOnPubDate`: recorded from about August 2025
- **Rabbithole's `gameState`:** `{currentQuestion, questionResults, score, status}`.
  - Each result is `correct_first_try`, `correct_with_hint`, `correct_with_choice` or `incorrect`.
- **No listing query:** there's no "list my games" query, so a history means asking for every date.
- **No stats endpoint:** stats are computed from saved games.

### How saved games behave

- **Sync** (from the games' code):
  - Games keep progress locally first.
  - When you're logged in, local saves are uploaded and then removed locally.
  - Local and server copies are merged by the newer `updatedAt`.
  - The server keeps one record per game, with no history.
- **The mobile app uploads lazily.** Its calendar shows history kept on the
  phone, and a puzzle's save is uploaded when you open that puzzle while
  logged in.
  - `createdAt` is when the server first saw the game.
  - `updatedAt` is when it was last played.
- **Saved games can go backward:**
  - The app has a "reset puzzle" button.
  - Opening a date can write an empty `notStarted` save, which, being newer, can replace a finished one.
  - A later fetch can therefore show less progress than an earlier one. Treat saved games as snapshots, and never write a save that's older or less complete than the server's.
- **Hard mode** (an app setting) hasn't been seen in saved games.
