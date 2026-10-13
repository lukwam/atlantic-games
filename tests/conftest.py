"""Fixtures for tests that run against both clients over mocked HTTP."""
import pytest
import respx

from tests.support import Api
from tests.support import cookies


@pytest.fixture(params=["sync", "async"])
def make(request):
    """Make a sync or async client."""
    return lambda **kwargs: Api(request.param, **kwargs)


@pytest.fixture
def api(make):
    return make()


@pytest.fixture
def logged_in(make):
    return make(cookies=cookies())


@pytest.fixture
def mock():
    with respx.mock(assert_all_called=False) as router:
        yield router
    # The library is read-only: every request any client test makes must be a
    # GET, and no GraphQL query may be a mutation.
    for call in router.calls:
        assert call.request.method == "GET", call.request
        query = call.request.url.params.get("query", "")
        assert not query.lstrip().startswith("mutation"), query
