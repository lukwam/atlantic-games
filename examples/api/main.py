"""Run your own Atlantic Games API.

    pip install "atlantic-games[api]"
    uvicorn main:app --reload

By default each request is made with the Atlantic login cookies (atljwt6 and
atljwt) sent to your API. Set ATLANTIC_COOKIES (for example "atljwt6=...") to use
your own cookies for every request instead, and keep the API private if you do.
"""
import os

from atlgames import AsyncAtlanticGamesClient
from atlgames.api import create_app
from atlgames.api import get_client

app = create_app(title="My Atlantic Games API")

if cookies := os.environ.get("ATLANTIC_COOKIES"):
    client = AsyncAtlanticGamesClient(cookies=cookies)
    app.dependency_overrides[get_client] = lambda: client


@app.get("/health", include_in_schema=False)
def health() -> dict:
    """Health check for your load balancer or container platform."""
    return {"status": "ok"}
