"""Cookie parsing and the account read from them. Every token here is made up."""
import datetime
import json

import pytest

from atlgames import Account
from atlgames import AtlanticGamesClient
from atlgames import parse_cookies
from atlgames.auth import account_from_cookies
from atlgames.auth import jwt_claims
from tests.support import USER_UUID
from tests.support import fake_jwt
from tests.support import session_token

TOKEN = session_token()
OTHER_UUID = "00000000-0000-4000-8000-000000000002"


@pytest.mark.parametrize("cookies", [
    {"atljwt6": TOKEN, "atljwt": "abc"},
    [{"name": "atljwt6", "value": TOKEN, "domain": ".theatlantic.com", "httpOnly": True},
     {"name": "atljwt", "value": "abc"}],
    f"atljwt6={TOKEN}; atljwt=abc",
    f"  atljwt6={TOKEN};atljwt=abc; ",
    json.dumps([{"name": "atljwt6", "value": TOKEN, "domain": ".theatlantic.com"}, {"name": "atljwt", "value": "abc"}],
               indent=2),
    json.dumps({"atljwt6": TOKEN, "atljwt": "abc"}),
])
def test_parse_cookies(cookies):
    """Cookies can be a dict, a Cookie-Editor JSON export (as a list or a
    string), a JSON object string or a Cookie header string."""
    assert parse_cookies(cookies) == {"atljwt6": TOKEN, "atljwt": "abc"}


def test_parse_bare_jwt():
    """A bare token is the atljwt6 cookie."""
    assert parse_cookies(TOKEN) == {"atljwt6": TOKEN}
    assert parse_cookies(f"  {TOKEN}\n") == {"atljwt6": TOKEN}


@pytest.mark.parametrize("cookies", [None, "", {}, []])
def test_parse_no_cookies(cookies):
    assert parse_cookies(cookies) == {}


def test_parse_header_values_with_equals_signs():
    assert parse_cookies("a=b=c; d=; junk") == {"a": "b=c", "d": ""}


@pytest.mark.parametrize("cookies", [
    {"atljwt6": "SECRET\nVALUE"},
    {"atljwt6": "SECRET;VALUE"},
    {"bad name": "SECRETVALUE"},
    '[{"name": "atljwt6", "value": "SECRETVALUE"',
    [{"name": "atljwt6"}, {"value": "SECRETVALUE"}],
    ["SECRETVALUE"],
])
def test_bad_cookies_never_show_their_values(cookies):
    with pytest.raises(ValueError) as info:
        parse_cookies(cookies)
    assert "SECRET" not in str(info.value)
    with pytest.raises(ValueError) as info:
        AtlanticGamesClient(cookies=cookies)
    assert "SECRET" not in str(info.value)


def test_jwt_claims():
    assert jwt_claims(TOKEN)["uuid"] == USER_UUID


@pytest.mark.parametrize("token", ["SECRET", "SECRET.%%%.x", "a.W10.c", "a.SECRETNOTJSON.c"])
def test_jwt_claims_errors_hide_the_token(token):
    with pytest.raises(ValueError) as info:
        jwt_claims(token)
    assert "SECRET" not in str(info.value) and "isn't a JWT" in str(info.value)


def test_account_from_session_cookie():
    account = account_from_cookies({"atljwt6": TOKEN})
    assert account.uuid == USER_UUID
    assert account.issued_at == datetime.datetime.fromtimestamp(1790000000, datetime.timezone.utc)
    assert account.expires_at == datetime.datetime.fromtimestamp(1792592000, datetime.timezone.utc)
    assert account.refresh_expires_at.year == 2027
    assert account.premium_access is None and account.ad_free is None


def test_account_with_entitlements():
    entitlements = fake_jwt({"uuid": USER_UUID, "premium_access": True, "paymeter_access": True,
                             "ad_free": False, "staff": False})
    account = account_from_cookies({"atljwt6": TOKEN, "atljwt": entitlements})
    assert (account.premium_access, account.paymeter_access, account.ad_free, account.staff) == (
        True, True, False, False)


def test_account_ignores_someone_elses_entitlements():
    entitlements = fake_jwt({"uuid": OTHER_UUID, "premium_access": True})
    assert account_from_cookies({"atljwt6": TOKEN, "atljwt": entitlements}).premium_access is None


def test_account_ignores_bad_entitlements():
    assert account_from_cookies({"atljwt6": TOKEN, "atljwt": "not-a-jwt"}).premium_access is None


def test_account_with_user_uuid_only():
    token = fake_jwt({"user_uuid": USER_UUID})
    entitlements = fake_jwt({"uuid": USER_UUID, "staff": True})
    account = account_from_cookies({"atljwt6": token, "atljwt": entitlements})
    assert account.uuid == USER_UUID and account.staff is True
    assert account.expires_at is None and not account.expired


def test_account_without_session_cookie():
    assert account_from_cookies({}) is None
    assert account_from_cookies({"atljwt": fake_jwt({"uuid": USER_UUID})}) is None
    assert AtlanticGamesClient().account is None


def test_account_without_user_id():
    with pytest.raises(ValueError, match="no user ID"):
        account_from_cookies({"atljwt6": fake_jwt({"sub": "someone"})})


def test_expired():
    old = session_token(exp=1000)
    assert account_from_cookies({"atljwt6": old}).expired
    assert not Account(uuid=USER_UUID).expired


def test_client_account():
    client = AtlanticGamesClient(cookies=f"atljwt6={TOKEN}")
    assert client.account.uuid == USER_UUID
