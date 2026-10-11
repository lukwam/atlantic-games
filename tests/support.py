"""Shared test helpers: fixture files, fake cookies and a sync/async client wrapper.

The fixtures in tests/fixtures are trimmed captures of real responses from
Bracket City's CloudFront files, Amuse Labs, The Atlantic's GraphQL API and
the Stacks site. Saved games and login tokens are made up.
"""
import base64
import functools
import json
from pathlib import Path

from atlgames import AsyncAtlanticGamesClient
from atlgames import AtlanticGamesClient
from atlgames import amuse

FIXTURES = Path(__file__).parent / "fixtures"
#: A made-up Atlantic user ID.
USER_UUID = "00000000-0000-4000-8000-000000000001"


def text(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


def load(path: str):
    return json.loads(text(path))


@functools.lru_cache
def _bracket_city() -> dict[str, dict]:
    return {p["puzzleDate"]: p for p in load("bracket_city/puzzles.json")}


def bracket_city_puzzles() -> list[dict]:
    """A few dozen real Bracket City puzzles, including every one whose
    caption differs from its solved text."""
    return [dict(p) for p in _bracket_city().values()]


def bracket_city_puzzle(date: str) -> dict:
    return dict(_bracket_city()[date])


def crossword_params(name: str) -> dict:
    return amuse.page_params(text(f"crossword/{name}.html"))


def crossword_page(params: dict, title: str = "A crossword") -> str:
    """An Amuse Labs puzzle page with these params."""
    return (f"<html><head><title>{title}</title></head><body>"
            f'<script type="application/json" id="params">{json.dumps(params)}</script></body></html>')


def b64json(data) -> str:
    return base64.b64encode(json.dumps(data).encode()).decode()


def fake_jwt(claims: dict) -> str:
    """An unsigned JWT with these claims (the client never verifies them)."""
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS256', 'typ': 'JWT'})}.{part(claims)}.ZmFrZS1zaWduYXR1cmU"


def session_token(uuid: str = USER_UUID, **claims) -> str:
    return fake_jwt({"uuid": uuid, "user_uuid": uuid, "token_type": "sliding",
                     "iat": 1790000000, "exp": 1792592000, "refresh_exp": 1821536000, **claims})


def cookies(uuid: str = USER_UUID) -> dict[str, str]:
    return {"atljwt6": session_token(uuid)}


class Api:
    """Calls a client method the same way for the sync and async clients."""

    def __init__(self, kind: str, **kwargs):
        self.kind = kind
        kwargs.setdefault("backoff", 0)
        cls = AtlanticGamesClient if kind == "sync" else AsyncAtlanticGamesClient
        self.client = cls(**kwargs)

    async def __call__(self, name: str, *args, **kwargs):
        result = getattr(self.client, name)(*args, **kwargs)
        if self.kind == "async":
            result = await result
        return result
