"""Cookies and the logged-in account.

The Atlantic keeps your login in the `atljwt6` cookie, an httpOnly JWT that
lasts 30 days. Its sibling `atljwt` carries your entitlements (premium
access, ad free, ...). Neither is verified here: the claims are read locally
so the client can say who you are and when the token expires, without a
request.
"""
import base64
import datetime
import json
import re
from typing import Any
from typing import Iterable
from typing import Mapping

from pydantic import BaseModel
from pydantic import ConfigDict

SESSION_COOKIE = "atljwt6"
ENTITLEMENTS_COOKIE = "atljwt"

Cookies = Mapping[str, str] | Iterable[Mapping[str, Any]] | str | None

COOKIE_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
COOKIE_VALUE_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f;]")


def parse_cookies(cookies: Cookies) -> dict[str, str]:
    """Return cookies as a dict.

    Accepts a dict of cookie names to values, a list of cookie objects with
    `name` and `value` keys (the Cookie-Editor JSON export format), either of
    those as a JSON string, a `Cookie` header string such as
    `"atljwt6=...; atljwt=..."`, or a bare `atljwt6` token.

    Raises ValueError for cookies that can't be sent, without including any
    cookie values in the message.
    """
    if not cookies:
        return {}
    if isinstance(cookies, str):
        text = cookies.strip()
        if text.startswith(("[", "{")):
            try:
                return parse_cookies(json.loads(text))
            except json.JSONDecodeError:
                raise ValueError("The cookies look like JSON but couldn't be read as JSON") from None
        if "=" not in text.split(".", 1)[0] and text.count(".") == 2 and ";" not in text:
            return check_cookies({SESSION_COOKIE: text})  # a bare JWT
        parsed = {}
        for part in text.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep:
                parsed[name.strip()] = value.strip()
        return check_cookies(parsed)
    if isinstance(cookies, Mapping):
        return check_cookies({str(k): str(v) for k, v in cookies.items()})
    try:
        return check_cookies({str(c["name"]): str(c["value"]) for c in cookies})
    except (KeyError, TypeError):
        raise ValueError("Cookie lists need a name and value for each cookie") from None


def check_cookies(cookies: dict[str, str]) -> dict[str, str]:
    """Raise ValueError if any cookie can't be sent in a Cookie header.

    The message names the cookie but never includes its value.
    """
    for name, value in cookies.items():
        if not COOKIE_NAME.match(name):
            raise ValueError("A cookie has an invalid name (cookie values aren't shown)")
        if COOKIE_VALUE_FORBIDDEN.search(value):
            raise ValueError(f"The {name} cookie's value has characters that can't be sent "
                             "(such as line breaks or semicolons); its value isn't shown")
    return cookies


def jwt_claims(token: str) -> dict:
    """Return a JWT's claims without verifying it. Raises ValueError if it
    isn't a JWT (the message never includes the token)."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise ValueError("The cookie isn't a JWT (its value isn't shown)") from None
    if not isinstance(claims, dict):
        raise ValueError("The cookie isn't a JWT (its value isn't shown)")
    return claims


def _time(seconds) -> datetime.datetime | None:
    if not isinstance(seconds, (int, float)):
        return None
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc)


class Account(BaseModel):
    """Who the cookies belong to, read from the cookies themselves.

    Entitlements come from the `atljwt` cookie, so they're None if you only
    gave `atljwt6`.
    """
    model_config = ConfigDict(extra="allow")

    #: Your Atlantic user ID. Amuse Labs keys your crossword plays by it.
    uuid: str
    issued_at: datetime.datetime | None = None
    #: When the login token stops working. The site renews it as you browse.
    expires_at: datetime.datetime | None = None
    #: The latest the token can be renewed to.
    refresh_expires_at: datetime.datetime | None = None
    premium_access: bool | None = None
    paymeter_access: bool | None = None
    ad_free: bool | None = None
    staff: bool | None = None

    @property
    def expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= datetime.datetime.now(datetime.timezone.utc))


def account_from_cookies(cookies: Mapping[str, str]) -> Account | None:
    """Return the Account for parsed cookies, or None without `atljwt6`."""
    token = cookies.get(SESSION_COOKIE)
    if not token:
        return None
    claims = jwt_claims(token)
    uuid = claims.get("user_uuid") or claims.get("uuid")
    if not uuid:
        raise ValueError(f"The {SESSION_COOKIE} cookie has no user ID; is it the right cookie?")
    entitlements = {}
    if cookies.get(ENTITLEMENTS_COOKIE):
        try:
            entitlements = jwt_claims(cookies[ENTITLEMENTS_COOKIE])
        except ValueError:
            pass
        if entitlements.get("uuid") not in (None, uuid, claims.get("uuid")):
            entitlements = {}  # someone else's cookie
    return Account(
        uuid=uuid,
        issued_at=_time(claims.get("iat")),
        expires_at=_time(claims.get("exp")),
        refresh_expires_at=_time(claims.get("refresh_exp")),
        **{k: entitlements.get(k) for k in ("premium_access", "paymeter_access", "ad_free", "staff")},
    )
