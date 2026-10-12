"""atlg: The Atlantic's games on the command line.

Requires the `cli` extra::

    pip install "atlantic-games[cli]"

To build your own command line on top of atlg, use the public API in
``atlgames.cli.extension``: ``create_app()``, ``run()``, ``emit()``,
``FormatOption`` and ``get_client()``. ``create_app`` and ``run`` can also be
imported from here.
"""
from typing import Any

_EXTENSION_NAMES = {"create_app", "run"}


def _missing_extra(err: ImportError) -> SystemExit:
    return SystemExit(
        f'atlg needs the cli extra ({err.name} is missing). Install it with:\n'
        '    pip install "atlantic-games[cli]"'
    )


def main() -> None:
    """Entry point for the atlg command."""
    try:
        from atlgames.cli.app import main as run_atlg
    except ImportError as err:
        raise _missing_extra(err) from None
    run_atlg()


def __getattr__(name: str) -> Any:
    """Import create_app and run lazily, so the base install doesn't need Typer."""
    if name in _EXTENSION_NAMES:
        from atlgames.cli import extension

        return getattr(extension, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
