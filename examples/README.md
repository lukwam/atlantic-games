# Examples

Small projects built on `atlantic-games`. Each is a single script.

| Example | What it does | Cookies |
|---|---|---|
| [bracket_city_depth.py](bracket_city_depth.py) | The most deeply nested Bracket City puzzles in a date range, using `puzzle.depth` | No |
| [clue_reuse.py](clue_reuse.py) | Answers that repeat across recent crosswords, and how each was clued, using `puzzle.entries()` | No |
| [bracket_city_efficiency.py](bracket_city_efficiency.py) | Your Bracket City keystroke efficiency by weekday | Yes |
| [api/](api) | Run your own Atlantic Games REST API, with a Dockerfile | Optional |

```bash
pip install atlantic-games
python bracket_city_depth.py --from 2026-09-01 --top 5
python clue_reuse.py --days 30
ATLANTIC_COOKIES="atljwt6=..." python bracket_city_efficiency.py --days 180
```

`clue_reuse.py` prints answers, so it contains spoilers for the crosswords it
looks at.
