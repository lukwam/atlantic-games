# Run your own Atlantic Games API

A minimal FastAPI app built on `atlgames.api`. Use it as a starting point for
your own `main.py` and container.

## Run locally

```bash
pip install "atlantic-games[api]"
uvicorn main:app --reload
```

Then open <http://localhost:8000/docs>.

## Run with Docker

```bash
docker build -t atlantic-games-api .
docker run -p 8080:8080 atlantic-games-api
```

Then open <http://localhost:8080/docs>.

## Cookies

Puzzles don't need cookies. Your saved games, stats and crossword progress
need your `atljwt6` cookie from a logged-in theatlantic.com session, which you
can send with each request:

```bash
curl -H "Cookie: atljwt6=..." http://localhost:8080/bracket-city/stats
```

Only the `atljwt6` and `atljwt` cookies are passed on, and only to The
Atlantic's API. To use your own cookies for every request instead, set
`ATLANTIC_COOKIES`:

```bash
docker run -p 8080:8080 -e ATLANTIC_COOKIES="atljwt6=..." atlantic-games-api
```

Anyone who can reach the API can then see your saved games and stats, so keep
it private. The `atljwt6` cookie lasts 30 days.
