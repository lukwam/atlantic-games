"""Check that the package, or an extra, works when installed alone.

Run in CI after `pip install .` (core) or `pip install ".[EXTRA]"`, with
PYTHONTZPATH="" so there's no system time zone database: New York time must
come from the package's own dependencies (tzdata).

    python scripts/check_extra.py core|cli|mcp
"""
import datetime
import sys

MODULES = {"core": "atlgames", "cli": "atlgames.cli.app", "mcp": "atlgames.mcp_server"}


def main() -> None:
    extra = sys.argv[1]
    __import__(MODULES[extra])
    from atlgames.models import EASTERN

    # New York is UTC-4 in summer and UTC-5 in winter.
    summer = datetime.datetime(2025, 7, 1, 12, tzinfo=EASTERN)
    winter = datetime.datetime(2025, 1, 1, 12, tzinfo=EASTERN)
    assert summer.utcoffset() == datetime.timedelta(hours=-4), summer.utcoffset()
    assert winter.utcoffset() == datetime.timedelta(hours=-5), winter.utcoffset()
    print(f"{extra}: {MODULES[extra]} imports, today in New York is {datetime.datetime.now(EASTERN).date()}")


if __name__ == "__main__":
    main()
